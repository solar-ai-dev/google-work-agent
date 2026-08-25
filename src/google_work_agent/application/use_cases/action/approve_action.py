"""Canonical persisted Application authority for explicit Action approval."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.approval_source_snapshot import (
    build_approval_source_snapshot,
)
from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_authority,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.application.coordinator import LocalRunCoordinator, QueueBusyError
from google_work_agent.application.feasibility import (
    approval_source_snapshot_for_feasibility,
    feasibility_authority,
    require_feasibility_approval,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_source_snapshot_for_task_duplicate,
    duplicate_authority,
    require_duplicate_acknowledgement,
)
from google_work_agent.application.write_execution_integrity import calculate_recovery_fingerprint
from google_work_agent.application.write_persistence import (
    action_response_from_result,
    audit_event,
    finish_json_receipt,
    require_action,
    require_plan,
    resolve_existing_action_receipt,
)
from google_work_agent.domain import (
    ActionStatus,
    ApprovalStatus,
    CalendarConflictDecision,
    EffectType,
    PolicyViolationError,
    ResultCode,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    canonicalize_json_value,
    next_allowed_action_commands,
)
from google_work_agent.ports import (
    ApprovalRecord,
    IdGenerator,
    PlanReviewStatus,
    PlanStatus,
    TraceEventRecord,
    UnitOfWork,
)


@dataclass(frozen=True, slots=True)
class ApproveActionCommand:
    command_id: str
    request_hash: str
    request_id: str
    action_id: str
    expected_version: int
    duplicate_acknowledged: bool = False
    calendar_conflict_acknowledged: bool = False


@dataclass(frozen=True, slots=True)
class ApproveActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    conflict_detail: str | None = None


class ApproveActionFollowupQueueBusyError(RuntimeError):
    def __init__(self, *, current_state: str) -> None:
        super().__init__("approval runtime resume is queued")
        self.current_state = current_state


class ApproveActionHandler:
    """Own durable approval semantics and server-side approval source authority."""

    def __init__(
        self,
        *,
        get_approval_ttl_minutes: Callable[[], int],
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        local_run_coordinator: LocalRunCoordinator,
        id_generator: IdGenerator,
    ) -> None:
        self._get_approval_ttl_minutes = get_approval_ttl_minutes
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._local_run_coordinator = local_run_coordinator
        self._id_generator = id_generator
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ApproveActionCommand) -> ApproveActionResult:
        ttl_ms = self._get_approval_ttl_minutes() * 60_000
        if ttl_ms <= 0:
            raise RuntimeError("approval_ttl_minutes must be positive")

        run_id: str | None = None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                replay = resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    now_ms=self._now_ms(),
                )
                result = self._result_from_response(replay)
                if result.applied:
                    action = require_action(unit_of_work, command.action_id)
                    plan = require_plan(unit_of_work, action.plan_id)
                    run_id = plan.run_id
                else:
                    return result
            else:
                now_ms = self._now_ms()
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="ApproveAction",
                    request_hash=command.request_hash,
                    aggregate_type="Action",
                    aggregate_id=command.action_id,
                    created_at_ms=now_ms,
                )
                action = require_action(unit_of_work, command.action_id)
                plan = require_plan(unit_of_work, action.plan_id)
                run = unit_of_work.runs.get_by_id(plan.run_id)
                if run is None:
                    raise LookupError(f"run not found: {plan.run_id}")
                conversation = unit_of_work.conversations.get(run.conversation_id)
                if conversation is None:
                    raise LookupError(f"conversation not found: {run.conversation_id}")
                entry = self._registry.require(action.tool_name)

                if plan.review_status is not PlanReviewStatus.PASSED:
                    result = ApproveActionResult(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
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
                        conflict_detail="plan review must pass after the latest action modification",
                    )
                    unit_of_work.audits.add(
                        audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="PLAN_REVIEW_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                "review_status": plan.review_status.value,
                                "review_version": plan.review_version,
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        result,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return result

                resource_ref = (
                    None
                    if action.target_resource_ref_id is None
                    else unit_of_work.resource_refs.get(action.target_resource_ref_id)
                )
                source_snapshot = build_approval_source_snapshot(
                    action=action,
                    plan_run_id=plan.run_id,
                    resource_ref=resource_ref,
                )
                duplicate_decision = None
                calendar_decision = None

                if action.tool_name == TASK_CREATE_TOOL and action.version == command.expected_version:
                    try:
                        duplicate_decision = require_duplicate_acknowledgement(
                            risk=action.risk,
                            acknowledged=command.duplicate_acknowledged,
                        )
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.add(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="TASK_DUPLICATE_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    "decision": (duplicate_authority(action.risk) or ("UNKNOWN", ()))[0],
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    source_snapshot = {
                        **source_snapshot,
                        **approval_source_snapshot_for_task_duplicate(
                            risk=action.risk,
                            acknowledged=command.duplicate_acknowledged,
                        ),
                    }

                if action.tool_name in CALENDAR_CONFLICT_TOOLS and action.version == command.expected_version:
                    try:
                        require_feasibility_approval(action.risk)
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.add(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="FEASIBILITY_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    **self._feasibility_audit_metadata(action.risk),
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    try:
                        calendar_decision = require_calendar_conflict_acknowledgement(
                            risk=action.risk,
                            acknowledged=command.calendar_conflict_acknowledged,
                        )
                    except PolicyViolationError as error:
                        result = self._blocked_result(action, str(error))
                        unit_of_work.audits.add(
                            audit_event(
                                run_id=plan.run_id,
                                action_id=action.id,
                                event_type="CALENDAR_CONFLICT_APPROVAL_BLOCKED",
                                outcome=ResultCode.STATE_CONFLICT.value,
                                metadata={
                                    "command_id": command.command_id,
                                    **self._calendar_conflict_audit_metadata(
                                        risk=action.risk, action_id=action.id
                                    ),
                                },
                                created_at_ms=now_ms,
                            )
                        )
                        finish_json_receipt(
                            unit_of_work, command.command_id, result, action.version, now_ms
                        )
                        unit_of_work.commit()
                        return result
                    source_snapshot = {
                        **source_snapshot,
                        **approval_source_snapshot_for_calendar_conflict(
                            risk=action.risk,
                            acknowledged=command.calendar_conflict_acknowledged,
                        ),
                        **approval_source_snapshot_for_feasibility(risk=action.risk),
                    }

                approval_result = unit_of_work.actions.approve_write(
                    action.id,
                    expected_version=command.expected_version,
                    updated_at_ms=now_ms,
                )
                if not approval_result.applied:
                    response = action_response_from_result(
                        action_id=action.id,
                        result=approval_result,
                    )
                    result = self._result_from_response(response)
                    finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        result,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return result

                source_snapshot_hash = calculate_canonical_json_hash(source_snapshot)
                approval = ApprovalRecord(
                    id=self._id_generator.next_id(),
                    action_id=action.id,
                    approval_no=len(unit_of_work.approvals.list_by_action(action.id)) + 1,
                    action_version=approval_result.current_version,
                    status=ApprovalStatus.ACTIVE,
                    approved_by_account_id=conversation.account_id,
                    approved_by_display=None,
                    arguments_snapshot_json=action.arguments_json,
                    canonical_arguments_hash=action.arguments_hash,
                    source_snapshot_json=canonicalize_json_value(source_snapshot),
                    source_snapshot_hash=source_snapshot_hash,
                    policy_version=entry.registry_version,
                    tool_schema_version=entry.input_schema_version,
                    idempotency_key=calculate_canonical_json_hash(
                        {
                            "operation": "ApproveActionIdempotencyKeyV1",
                            "payload": {
                                "action_id": action.id,
                                "command_id": command.command_id,
                            },
                        }
                    ),
                    recovery_fingerprint=calculate_recovery_fingerprint(
                        tool_name=action.tool_name,
                        arguments_hash=action.arguments_hash,
                        source_snapshot_hash=source_snapshot_hash,
                    ),
                    approved_at_ms=now_ms,
                    expires_at_ms=now_ms + ttl_ms,
                    consumed_at_ms=None,
                )
                unit_of_work.approvals.insert(approval)

                if plan.status is PlanStatus.WAITING_APPROVAL:
                    unit_of_work.plans.activate_waiting(plan.id)

                unit_of_work.traces.add(
                    TraceEventRecord(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="WRITE_ACTION_APPROVED",
                        status=ActionStatus.APPROVED.value,
                        duration_ms=None,
                        payload_json=dumps(
                            {"approval_id": approval.id, "command_id": command.command_id},
                            sort_keys=True,
                        ),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.add(
                    audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="WRITE_APPROVED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={"approval_id": approval.id, "command_id": command.command_id},
                        created_at_ms=now_ms,
                    )
                )
                if (
                    action.tool_name == TASK_CREATE_TOOL
                    and duplicate_decision is not None
                    and duplicate_decision.value != "NOT_DUPLICATE"
                ):
                    unit_of_work.audits.add(
                        audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="TASK_DUPLICATE_OVERRIDE_ACKNOWLEDGED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata={
                                "approval_id": approval.id,
                                "decision": duplicate_decision.value,
                            },
                            created_at_ms=now_ms,
                        )
                    )
                if (
                    action.tool_name in CALENDAR_CONFLICT_TOOLS
                    and calendar_decision is not None
                    and calendar_decision is not CalendarConflictDecision.NO_CONFLICT
                ):
                    unit_of_work.audits.add(
                        audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="CALENDAR_CONFLICT_OVERRIDE_ACKNOWLEDGED",
                            outcome=ResultCode.TRANSITION_APPLIED.value,
                            metadata={
                                "approval_id": approval.id,
                                **self._calendar_conflict_audit_metadata(
                                    risk=action.risk, action_id=action.id
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )

                result = ApproveActionResult(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    action_id=action.id,
                    action_status=approval_result.current_status.value,
                    action_version=approval_result.current_version,
                    next_allowed_commands=tuple(
                        item.value for item in approval_result.next_allowed_commands
                    ),
                )
                finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    result,
                    approval_result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                run_id = plan.run_id

        if run_id is not None:
            try:
                self._local_run_coordinator.enqueue_resume(
                    run_id=run_id,
                    request_id=command.request_id,
                    command_id=command.command_id,
                    resume_kind="APPROVAL",
                    resume_payload={"approved": True},
                )
            except QueueBusyError as error:
                raise ApproveActionFollowupQueueBusyError(
                    current_state=result.action_status
                ) from error
        return result

    @staticmethod
    def _result_from_response(response: object) -> ApproveActionResult:
        return ApproveActionResult(
            applied=bool(response.applied),
            result_code=str(response.result_code),
            action_id=str(response.action_id),
            action_status=str(response.action_status),
            action_version=int(response.action_version),
            next_allowed_commands=tuple(response.next_allowed_commands),
            conflict_detail=getattr(response, "conflict_detail", None),
        )

    @staticmethod
    def _blocked_result(action: object, detail: str) -> ApproveActionResult:
        effect_type = EffectType(action.effect_type)
        status = ActionStatus(action.status)
        return ApproveActionResult(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            action_id=str(action.id),
            action_status=status.value,
            action_version=int(action.version),
            next_allowed_commands=tuple(
                item.value for item in next_allowed_action_commands(status, effect_type=effect_type)
            ),
            conflict_detail=detail,
        )

    @staticmethod
    def _calendar_conflict_audit_metadata(
        *, risk: dict[str, object], action_id: str
    ) -> dict[str, object]:
        authority = calendar_conflict_authority(risk) or ("UNKNOWN", ())
        value = risk.get("calendar_conflict")
        return {
            "action_id": action_id,
            "decision": authority[0],
            "matched_resource_ids": list(authority[1]),
            "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
            "freshness": value.get("freshness", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN",
        }

    @staticmethod
    def _feasibility_audit_metadata(risk: dict[str, object]) -> dict[str, object]:
        value = risk.get("feasibility")
        authority = feasibility_authority(risk)
        return {
            "decision": authority[0] if authority is not None else "UNKNOWN",
            "reason_codes": value.get("reason_codes", []) if isinstance(value, dict) else [],
            "required_duration": (
                value.get("required_duration_minutes") if isinstance(value, dict) else None
            ),
            "freshness": value.get("freshness", "UNKNOWN") if isinstance(value, dict) else "UNKNOWN",
        }
