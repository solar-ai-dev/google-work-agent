"""Canonical persisted application use case for Action modification."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from json import dumps, loads
from typing import cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    CalendarConflictGateway,
    CalendarConflictValidator,
    calendar_conflict_authority,
    merge_calendar_conflict_risk,
)
from google_work_agent.application.coordinator import LocalRunCoordinator, QueueBusyError
from google_work_agent.application.feasibility import (
    FeasibilityGateway,
    FeasibilityValidator,
    feasibility_authority,
    merge_feasibility_risk,
    refresh_feasibility_input_for_arguments,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    TaskDuplicateValidator,
    TaskListGateway,
    duplicate_authority,
    merge_duplicate_risk,
)
from google_work_agent.application.write_persistence import (
    audit_event,
    emit_command_rejected_hash_mismatch,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CalendarWorkHours,
    EffectType,
    EvidencePolicyInput,
    ResultCode,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    next_allowed_action_commands,
    validate_evidence_policy,
)
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.ports import (
    ActionRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    PlanReviewStatus,
    TraceEventRecord,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_MODIFIABLE_ACTION_STATUSES = frozenset(
    {
        ActionStatus.PROPOSED.value,
        ActionStatus.MODIFIED.value,
        ActionStatus.APPROVED.value,
        ActionStatus.EXPIRED.value,
        ActionStatus.FAILED.value,
    }
)


@dataclass(frozen=True, slots=True)
class ModifyActionCommand:
    command_id: str
    request_hash: str
    request_id: str
    action_id: str
    expected_version: int
    arguments_patch: dict[str, object]


@dataclass(frozen=True, slots=True)
class ModifyActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    request_replayed: bool = False
    conflict_detail: str | None = None


class ModifyActionFollowupQueueBusyError(RuntimeError):
    def __init__(self, *, current_state: str) -> None:
        super().__init__("modified action review is queued")
        self.current_state = current_state


class ModifyActionHandler:
    """Persist a user modification and invalidate all stale write authority."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: TaskListGateway | CalendarConflictGateway,
        local_run_coordinator: LocalRunCoordinator,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._local_run_coordinator = local_run_coordinator
        self._registry = build_p0_tool_registry()
        self._task_duplicates = TaskDuplicateValidator(
            gateway=cast(TaskListGateway, gateway), now_ms=now_ms
        )
        self._calendar_conflicts = CalendarConflictValidator(
            gateway=cast(CalendarConflictGateway, gateway),
            now_ms=now_ms,
            work_hours_provider=work_hours_provider
            or (lambda: CalendarWorkHours(timezone="Asia/Seoul")),
        )
        self._feasibility = FeasibilityValidator(
            gateway=cast(FeasibilityGateway, gateway),
            now_ms=now_ms,
            work_hours_provider=work_hours_provider
            or (lambda: CalendarWorkHours(timezone="Asia/Seoul")),
        )

    def __call__(self, command: ModifyActionCommand) -> ModifyActionResult:
        fresh_duplicate_risk: dict[str, object] | None = None
        duplicate_arguments: dict[str, object] | None = None
        fresh_calendar_risk: dict[str, object] | None = None
        calendar_arguments: dict[str, object] | None = None
        feasibility_seed_risk: dict[str, object] | None = None
        fresh_feasibility_risk: dict[str, object] | None = None

        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(unit_of_work, existing, command)
            snapshot = self._require_action(unit_of_work, command.action_id)
            if (
                snapshot.tool_name == TASK_CREATE_TOOL
                and snapshot.status in _MODIFIABLE_ACTION_STATUSES
                and snapshot.version == command.expected_version
            ):
                entry = self._registry.require(snapshot.tool_name)
                if not (set(command.arguments_patch) - entry.modify_patchable_fields):
                    proposed = self._apply_arguments_patch(
                        loads(snapshot.arguments_json), command.arguments_patch
                    )
                    if calculate_canonical_json_hash(proposed) != snapshot.arguments_hash:
                        duplicate_arguments = proposed
            if (
                snapshot.tool_name in CALENDAR_CONFLICT_TOOLS
                and snapshot.status in _MODIFIABLE_ACTION_STATUSES
                and snapshot.version == command.expected_version
            ):
                entry = self._registry.require(snapshot.tool_name)
                if not (set(command.arguments_patch) - entry.modify_patchable_fields):
                    proposed = self._apply_arguments_patch(
                        loads(snapshot.arguments_json), command.arguments_patch
                    )
                    if calculate_canonical_json_hash(proposed) != snapshot.arguments_hash:
                        calendar_arguments = proposed
                        feasibility_seed_risk = refresh_feasibility_input_for_arguments(
                            risk=snapshot.risk, arguments=proposed
                        )

        if duplicate_arguments is not None:
            fresh_duplicate_risk = self._task_duplicates.fresh_risk(duplicate_arguments)
        if calendar_arguments is not None:
            fresh_calendar_risk = self._calendar_conflicts.fresh_risk(calendar_arguments)
            if feasibility_seed_risk is not None:
                fresh_feasibility_risk = self._feasibility.fresh_risk(
                    arguments=calendar_arguments, risk=feasibility_seed_risk
                )

        run_id: str | None = None
        plan_id: str | None = None
        review_version: int | None = None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return self._resolve_existing_receipt(unit_of_work, existing, command)

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ModifyAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = self._require_action(unit_of_work, command.action_id)
            effect_type = EffectType(action.effect_type)

            if effect_type is EffectType.READ or action.status not in _MODIFIABLE_ACTION_STATUSES:
                return self._finish(
                    unit_of_work,
                    command,
                    self._result(
                        action=action,
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT,
                        conflict_detail=(
                            "modify_action requires a PROPOSED, MODIFIED, APPROVED, "
                            "EXPIRED or FAILED write action"
                        ),
                    ),
                    now_ms,
                )

            entry = self._registry.require(action.tool_name)
            unknown_fields = sorted(set(command.arguments_patch) - entry.modify_patchable_fields)
            if unknown_fields:
                return self._finish(
                    unit_of_work,
                    command,
                    self._result(
                        action=action,
                        applied=False,
                        result_code=ResultCode.SCHEMA_VIOLATION,
                        conflict_detail=f"unsupported arguments_patch fields: {unknown_fields}",
                    ),
                    now_ms,
                )

            new_arguments = self._apply_arguments_patch(
                loads(action.arguments_json), command.arguments_patch
            )
            new_arguments_hash = calculate_canonical_json_hash(new_arguments)
            if new_arguments_hash == action.arguments_hash:
                return self._finish(
                    unit_of_work,
                    command,
                    self._result(
                        action=action,
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT,
                        conflict_detail="arguments_patch does not change any canonical argument value",
                    ),
                    now_ms,
                )

            validate_evidence_policy(
                EvidencePolicyInput(
                    evidence_count=len(unit_of_work.evidence.list_by_action(action.id)),
                    requires_existing_resource=effect_type in {EffectType.UPDATE, EffectType.DELETE},
                    has_user_selected_resource=action.target_resource_ref_id is not None,
                    has_explicit_resource_relation=action.target_resource_ref_id is not None,
                )
            )

            updated_risk = (
                merge_duplicate_risk(action.risk, fresh_duplicate_risk)
                if fresh_duplicate_risk is not None
                else action.risk
            )
            if fresh_calendar_risk is not None:
                updated_risk = merge_calendar_conflict_risk(updated_risk, fresh_calendar_risk)
            if feasibility_seed_risk is not None:
                updated_risk = feasibility_seed_risk
                if fresh_duplicate_risk is not None:
                    updated_risk = merge_duplicate_risk(updated_risk, fresh_duplicate_risk)
                if fresh_calendar_risk is not None:
                    updated_risk = merge_calendar_conflict_risk(updated_risk, fresh_calendar_risk)
            if fresh_feasibility_risk is not None:
                updated_risk = merge_feasibility_risk(updated_risk, fresh_feasibility_risk)

            preview = transition_modify_action(
                ActionStatus(action.status),
                action.version,
                command.expected_version,
                effect_type=effect_type,
            )
            revoked_approval_ids: tuple[str, ...] = ()
            if preview.applied:
                revoked_approval_ids = unit_of_work.approvals.revoke_active_by_action(action.id)

            mutation = unit_of_work.actions.modify_write(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
                arguments_json=canonicalize_json_value(new_arguments),
                arguments_hash=new_arguments_hash,
                risk=updated_risk,
            )
            if not mutation.applied:
                return self._finish(
                    unit_of_work,
                    command,
                    ModifyActionResult(
                        applied=False,
                        result_code=mutation.result_code.value,
                        action_id=action.id,
                        action_status=mutation.current_status.value,
                        action_version=mutation.current_version,
                        next_allowed_commands=tuple(
                            item.value for item in mutation.next_allowed_commands
                        ),
                        conflict_detail=mutation.conflict_detail,
                    ),
                    now_ms,
                )

            run_id = self._run_id_for_action(unit_of_work, action.id)
            plan_id = action.plan_id
            review_version = unit_of_work.plans.require_review(action.plan_id)
            self._revoke_stale_dependent_approvals(
                unit_of_work=unit_of_work,
                modified_action_id=action.id,
                run_id=run_id,
                command_id=command.command_id,
                now_ms=now_ms,
            )

            response = ModifyActionResult(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=mutation.current_status.value,
                action_version=mutation.current_version,
                next_allowed_commands=tuple(
                    item.value
                    for item in mutation.next_allowed_commands
                    if item is not ActionCommand.APPROVE_ACTION
                ),
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="ACTION_MODIFIED",
                    status=mutation.current_status.value,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="ACTION_MODIFIED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "command_id": command.command_id,
                        "revoked_approval_ids": list(revoked_approval_ids),
                        "plan_id": action.plan_id,
                        "review_version": review_version,
                    },
                    created_at_ms=now_ms,
                )
            )
            self._record_freshness_audits(
                unit_of_work=unit_of_work,
                action=action,
                run_id=run_id,
                updated_risk=updated_risk,
                fresh_duplicate_risk=fresh_duplicate_risk,
                fresh_calendar_risk=fresh_calendar_risk,
                fresh_feasibility_risk=fresh_feasibility_risk,
                now_ms=now_ms,
            )
            result = self._finish(unit_of_work, command, response, now_ms)

        if run_id is not None and plan_id is not None and review_version is not None:
            with self._unit_of_work_factory() as unit_of_work:
                plan = unit_of_work.plans.get_by_id(plan_id)
                if plan is None:
                    raise LookupError(f"plan not found: {plan_id}")
                review_required = plan.review_status is PlanReviewStatus.REQUIRED
            if review_required:
                try:
                    self._local_run_coordinator.enqueue_resume(
                        run_id=run_id,
                        request_id=command.request_id,
                        command_id=command.command_id,
                        resume_kind="MODIFY_REVIEW",
                        resume_payload={
                            "resume_kind": "MODIFY_REVIEW",
                            "plan_id": plan_id,
                            "review_version": review_version,
                        },
                    )
                except QueueBusyError as error:
                    raise ModifyActionFollowupQueueBusyError(
                        current_state=result.action_status
                    ) from error
        return result

    def _resolve_existing_receipt(
        self,
        unit_of_work: UnitOfWork,
        receipt: CommandReceiptRecord,
        command: ModifyActionCommand,
    ) -> ModifyActionResult:
        if receipt.request_hash != command.request_hash:
            emit_command_rejected_hash_mismatch(
                unit_of_work=unit_of_work,
                receipt=receipt,
                run_id=None,
                action_id=command.action_id,
                now_ms=self._now_ms(),
            )
            action = unit_of_work.actions.get_by_id(command.action_id)
            if action is None:
                return ModifyActionResult(
                    applied=False,
                    result_code=ResultCode.DUPLICATE_COMMAND.value,
                    action_id=command.action_id,
                    action_status="UNKNOWN",
                    action_version=receipt.result_version or 0,
                    next_allowed_commands=(),
                    request_replayed=True,
                    conflict_detail="command_id already exists with a different request_hash",
                )
            return replace(
                self._result(
                    action=action,
                    applied=False,
                    result_code=ResultCode.DUPLICATE_COMMAND,
                    conflict_detail="command_id already exists with a different request_hash",
                ),
                request_replayed=True,
            )
        if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
            raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
        payload = loads(receipt.response_json)
        if not isinstance(payload, dict):
            raise RuntimeError("modify receipt response must be an object")
        payload.setdefault("request_replayed", False)
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
        return replace(ModifyActionResult(**payload), request_replayed=True)

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        command: ModifyActionCommand,
        response: ModifyActionResult,
        now_ms: int,
    ) -> ModifyActionResult:
        unit_of_work.command_receipts.finish_json(
            command_id=command.command_id,
            applied=response.applied,
            result_code=ResultCode(response.result_code),
            result_version=response.action_version,
            response_json=dumps(asdict(response), sort_keys=True),
            completed_at_ms=now_ms,
        )
        unit_of_work.commit()
        return response

    @staticmethod
    def _result(
        *,
        action: ActionRecord,
        applied: bool,
        result_code: ResultCode,
        conflict_detail: str | None,
    ) -> ModifyActionResult:
        return ModifyActionResult(
            applied=applied,
            result_code=result_code.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=tuple(
                item.value
                for item in next_allowed_action_commands(
                    ActionStatus(action.status),
                    effect_type=EffectType(action.effect_type),
                )
            ),
            conflict_detail=conflict_detail,
        )

    @staticmethod
    def _apply_arguments_patch(
        current_arguments: dict[str, object], patch: dict[str, object]
    ) -> dict[str, object]:
        if not patch:
            return current_arguments
        merged = dict(current_arguments)
        payload = current_arguments.get("payload")
        new_payload = dict(payload) if isinstance(payload, dict) else {}
        new_payload.update(patch)
        merged["payload"] = new_payload
        return merged

    @staticmethod
    def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
        action = unit_of_work.actions.get_by_id(action_id)
        if action is None:
            raise LookupError(f"action not found: {action_id}")
        return action

    @classmethod
    def _run_id_for_action(cls, unit_of_work: UnitOfWork, action_id: str) -> str:
        action = cls._require_action(unit_of_work, action_id)
        plan = unit_of_work.plans.get_by_id(action.plan_id)
        if plan is None:
            raise LookupError(f"plan not found for action: {action_id}")
        return plan.run_id

    @staticmethod
    def _revoke_stale_dependent_approvals(
        *,
        unit_of_work: UnitOfWork,
        modified_action_id: str,
        run_id: str,
        command_id: str,
        now_ms: int,
    ) -> None:
        for dependent_id in unit_of_work.action_dependencies.list_dependents(modified_action_id):
            dependent = unit_of_work.actions.get_by_id(dependent_id)
            if dependent is None or dependent.status != ActionStatus.APPROVED.value:
                continue
            revoked_ids = unit_of_work.approvals.revoke_active_by_action(dependent_id)
            if not revoked_ids:
                continue
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=dependent_id,
                    event_type="ACTION_DEPENDENT_APPROVAL_REVOKED",
                    status=dependent.status,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "command_id": command_id,
                            "modified_action_id": modified_action_id,
                            "revoked_approval_ids": list(revoked_ids),
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=run_id,
                    action_id=dependent_id,
                    event_type="ACTION_DEPENDENT_APPROVAL_REVOKED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "command_id": command_id,
                        "modified_action_id": modified_action_id,
                        "revoked_approval_ids": list(revoked_ids),
                    },
                    created_at_ms=now_ms,
                )
            )

    @staticmethod
    def _record_freshness_audits(
        *,
        unit_of_work: UnitOfWork,
        action: ActionRecord,
        run_id: str,
        updated_risk: dict[str, object],
        fresh_duplicate_risk: dict[str, object] | None,
        fresh_calendar_risk: dict[str, object] | None,
        fresh_feasibility_risk: dict[str, object] | None,
        now_ms: int,
    ) -> None:
        authority = duplicate_authority(updated_risk) if fresh_duplicate_risk is not None else None
        if authority is not None:
            unit_of_work.audits.add(
                audit_event(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="TASK_DUPLICATE_CHECKED",
                    outcome="FRESH_GOOGLE_GET",
                    metadata={
                        "decision": authority[0],
                        "matched_count": len(authority[1]),
                        "freshness": "FRESH_GOOGLE_GET",
                    },
                    created_at_ms=now_ms,
                )
            )
        calendar_authority = calendar_conflict_authority(updated_risk) if fresh_calendar_risk is not None else None
        if calendar_authority is not None:
            risk_value = updated_risk.get("calendar_conflict")
            unit_of_work.audits.add(
                audit_event(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="CALENDAR_CONFLICT_CHECKED",
                    outcome="FRESH_GOOGLE_GET",
                    metadata={
                        "action_id": action.id,
                        "decision": calendar_authority[0],
                        "matched_resource_ids": list(calendar_authority[1]),
                        "reason_codes": risk_value.get("reason_codes", []) if isinstance(risk_value, dict) else [],
                        "freshness": "FRESH_GOOGLE_GET",
                    },
                    created_at_ms=now_ms,
                )
            )
        feasibility = feasibility_authority(updated_risk) if fresh_feasibility_risk is not None else None
        if feasibility is not None:
            value = updated_risk.get("feasibility")
            unit_of_work.audits.add(
                audit_event(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="FEASIBILITY_CHECKED",
                    outcome="FRESH_GOOGLE_GET",
                    metadata={
                        "decision": feasibility[0],
                        "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
                        "required_duration": value.get("required_duration_minutes") if isinstance(value, dict) else None,
                        "freshness": "FRESH_GOOGLE_GET",
                    },
                    created_at_ms=now_ms,
                )
            )
