"""User review mutations for persisted write actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from json import dumps, loads
from re import fullmatch
from typing import cast

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    CalendarConflictGateway,
    CalendarConflictValidator,
    calendar_conflict_authority,
    merge_calendar_conflict_risk,
)
from google_work_agent.application.feasibility import (
    FeasibilityGateway,
    FeasibilityValidator,
    feasibility_authority,
    merge_feasibility_risk,
    refresh_feasibility_input_for_arguments,
)
from google_work_agent.application.persistence_cas import update_action_record, update_plan_record
from google_work_agent.application.policy import EvidencePolicyInput, validate_evidence_policy
from google_work_agent.application.policy_kernels.calendar_conflict import CalendarWorkHours
from google_work_agent.application.run_command_receipts import (
    ActionMutationReceiptResponse as _ActionMutationResponse,
)
from google_work_agent.application.run_command_receipts import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.run_command_receipts import (
    resolve_existing_receipt as _resolve_existing_receipt,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    TaskDuplicateValidator,
    TaskListGateway,
    duplicate_authority,
    merge_duplicate_risk,
)
from google_work_agent.application.write_action_mutation_contracts import (
    ModifyWriteActionCommand,
    RejectWriteActionCommand,
)
from google_work_agent.application.write_persistence import (
    require_plan_review,
    revoke_active_approvals,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import (
    ActionCommand,
    ActionStatusV1,
    EffectType,
    next_allowed_action_commands,
)
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.results import CommandResult, ResultCode
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)
from google_work_agent.domain.run.transitions.complete_write_run import (
    transition_complete_write_run,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    UnitOfWork,
)
from google_work_agent.ports.connector.migration_contracts.tool_registry import (
    build_p0_tool_registry,
)
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple

_MODIFIABLE_ACTION_STATUSES = frozenset(
    {ActionStatusV1.PROPOSED.value, ActionStatusV1.MODIFIED.value, ActionStatusV1.APPROVED.value}
)


class ModifyWriteActionService:
    """Apply a user-supplied ``arguments_patch`` to a write action (FN-052)
    and revoke any Approval it invalidates.

    Scope is deliberately narrower than the bare domain transition table:
    only ``PROPOSED``, ``MODIFIED`` and ``APPROVED`` write actions may be content-edited
    here. ``FAILED`` retries go through ``prepare_write_retry`` and
    ``EXPIRED`` refresh is a separate, not-yet-implemented
    ``refresh_expired_action`` command -- both keep their own contracts
    instead of being reachable through this endpoint.

    FN-052 also requires: (1) only its own fixed field list per tool is
    patchable -- see ``ToolRegistryEntry.modify_patchable_fields``, which is
    intentionally narrower than a tool's raw MCP dispatch capability; (2) a
    no-op patch (empty, or equal to the current Canonical Arguments) applies
    nothing and must not revoke an ACTIVE Approval; (3) Schema and Policy are
    re-checked (field allowlist + ``validate_evidence_policy``); (3) Task
    duplicate validation is refreshed outside the write transaction while
    Calendar conflict validation remains a separate FN-032 gap; (4) direct
    dependents of the modified action that are already APPROVED have their
    ACTIVE Approval revoked too, so a stale dependent Approval can never
    authorize a Claim -- see ``_revoke_stale_dependent_approvals``.
    """

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: TaskListGateway | CalendarConflictGateway,
        work_hours_provider: Callable[[], CalendarWorkHours] | None = None,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
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

    def __call__(self, command: ModifyWriteActionCommand) -> dict[str, object]:
        fresh_duplicate_risk: dict[str, object] | None = None
        duplicate_arguments: dict[str, object] | None = None
        fresh_calendar_risk: dict[str, object] | None = None
        calendar_arguments: dict[str, object] | None = None
        feasibility_seed_risk: dict[str, object] | None = None
        fresh_feasibility_risk: dict[str, object] | None = None
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    dict[str, object],
                    asdict(
                        cast(
                            _ActionMutationResponse,
                            _resolve_existing_receipt(
                                unit_of_work=unit_of_work,
                                receipt=existing,
                                request_hash=command.request_hash,
                                response_type=_ActionMutationResponse,
                                action_id=command.action_id,
                                now_ms=self._now_ms(),
                            ),
                        )
                    ),
                )
            snapshot = _require_action(unit_of_work, command.action_id)
            if (
                snapshot.tool_name == TASK_CREATE_TOOL
                and snapshot.status in _MODIFIABLE_ACTION_STATUSES
                and snapshot.version == command.expected_version
            ):
                entry = self._registry.require(snapshot.tool_name)
                if not (set(command.arguments_patch) - entry.modify_patchable_fields):
                    proposed = _apply_arguments_patch(
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
                    proposed = _apply_arguments_patch(
                        loads(snapshot.arguments_json), command.arguments_patch
                    )
                    if calculate_canonical_json_hash(proposed) != snapshot.arguments_hash:
                        calendar_arguments = proposed
                        feasibility_seed_risk = refresh_feasibility_input_for_arguments(
                            risk=snapshot.risk, arguments=proposed
                        )

        # Phase 2: the Google read is deliberately outside every UnitOfWork.
        if duplicate_arguments is not None:
            fresh_duplicate_risk = self._task_duplicates.fresh_risk(duplicate_arguments)
        if calendar_arguments is not None:
            fresh_calendar_risk = self._calendar_conflicts.fresh_risk(calendar_arguments)
            if feasibility_seed_risk is not None:
                fresh_feasibility_risk = self._feasibility.fresh_risk(
                    arguments=calendar_arguments, risk=feasibility_seed_risk
                )

        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    dict[str, object],
                    asdict(
                        cast(
                            _ActionMutationResponse,
                            _resolve_existing_receipt(
                                unit_of_work=unit_of_work,
                                receipt=existing,
                                request_hash=command.request_hash,
                                response_type=_ActionMutationResponse,
                                action_id=command.action_id,
                                now_ms=self._now_ms(),
                            ),
                        )
                    ),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ModifyWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            effect_type = EffectType(action.effect_type)
            plan = unit_of_work.plans.load_bundle(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            current_plan = max(
                current_plan_tuple(unit_of_work.plans, plan.run_id),
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )

            if effect_type is EffectType.READ or action.status not in _MODIFIABLE_ACTION_STATUSES:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=(
                            "modify_action requires a PROPOSED, MODIFIED or APPROVED write action; "
                            "use prepare-retry for FAILED actions"
                        ),
                    ),
                )

            entry = self._registry.require(action.tool_name)
            unknown_fields = sorted(set(command.arguments_patch) - entry.modify_patchable_fields)
            if unknown_fields:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.SCHEMA_VIOLATION.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=f"unsupported arguments_patch fields: {unknown_fields}",
                    ),
                )

            new_arguments = _apply_arguments_patch(
                loads(action.arguments_json), command.arguments_patch
            )
            new_arguments_hash = calculate_canonical_json_hash(new_arguments)

            # FN-052 no-op guard: a patch that is empty, or that only restates
            # fields already equal to the current Canonical Arguments, must
            # not mutate anything. In particular it must never revoke an
            # existing ACTIVE Approval -- there is nothing to re-approve.
            if new_arguments_hash == action.arguments_hash:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status), effect_type=effect_type
                            )
                        ),
                        conflict_detail=(
                            "arguments_patch does not change any canonical argument value"
                        ),
                    ),
                )

            # Evidence/target linkage cannot change through a Modify patch, so
            # this reuses the exact inputs already satisfied when the action
            # was first planned -- a defensive re-check, not a new gate.
            evidence_count = len(unit_of_work.evidence.list_for_action(action.id))
            validate_evidence_policy(
                EvidencePolicyInput(
                    evidence_count=evidence_count,
                    requires_existing_resource=effect_type
                    in {EffectType.UPDATE, EffectType.DELETE},
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
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            revoked_approval_ids: tuple[str, ...] = ()
            if preview.applied:
                revoked_approval_ids = revoke_active_approvals(unit_of_work, action.id)
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=preview.current_status,
                        updated_at_ms=now_ms,
                        arguments_json=canonicalize_json_value(new_arguments),
                        arguments_hash=calculate_canonical_json_hash(new_arguments),
                        risk=updated_risk,
                    )
                    is None
                ):
                    raise RuntimeError("validated ModifyAction CAS failed")
            result = preview
            if not result.applied:
                return self._finish(
                    unit_of_work,
                    command=command,
                    now_ms=now_ms,
                    response=_ActionMutationResponse(
                        applied=False,
                        result_code=result.result_code.value,
                        action_id=action.id,
                        action_status=result.current_status.value,
                        action_version=result.current_version,
                        next_allowed_commands=tuple(
                            item.value for item in result.next_allowed_commands
                        ),
                        conflict_detail=result.conflict_detail,
                    ),
                )

            # A stale ACTIVE Approval must never authorize execution of the
            # arguments it was not issued for. Revoking is a no-op when the
            # action was PROPOSED and had no Approval yet.
            run_id = _run_id_for_action(unit_of_work, action.id)
            review_version = require_plan_review(unit_of_work, action.plan_id)
            _revoke_stale_dependent_approvals(
                unit_of_work=unit_of_work,
                modified_action_id=action.id,
                run_id=run_id,
                command_id=command.command_id,
                now_ms=now_ms,
            )

            response = _ActionMutationResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(
                    item.value
                    for item in result.next_allowed_commands
                    if item is not ActionCommand.APPROVE_ACTION
                ),
            )
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=action.id,
                    event_type="ACTION_MODIFIED",
                    status=result.current_status.value,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                _modify_audit_event(
                    run_id=run_id,
                    action_id=action.id,
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
            authority = (
                duplicate_authority(updated_risk) if fresh_duplicate_risk is not None else None
            )
            if authority is not None:
                unit_of_work.audits.append(
                    _modify_audit_event(
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
            calendar_authority = (
                calendar_conflict_authority(updated_risk)
                if fresh_calendar_risk is not None
                else None
            )
            if calendar_authority is not None:
                risk_value = updated_risk.get("calendar_conflict")
                unit_of_work.audits.append(
                    _modify_audit_event(
                        run_id=run_id,
                        action_id=action.id,
                        event_type="CALENDAR_CONFLICT_CHECKED",
                        outcome="FRESH_GOOGLE_GET",
                        metadata={
                            "action_id": action.id,
                            "decision": calendar_authority[0],
                            "matched_resource_ids": list(calendar_authority[1]),
                            "reason_codes": (
                                risk_value.get("reason_codes", [])
                                if isinstance(risk_value, dict)
                                else []
                            ),
                            "freshness": "FRESH_GOOGLE_GET",
                        },
                        created_at_ms=now_ms,
                    )
                )
            feasibility = (
                feasibility_authority(updated_risk) if fresh_feasibility_risk is not None else None
            )
            if feasibility is not None:
                value = updated_risk.get("feasibility")
                unit_of_work.audits.append(
                    _modify_audit_event(
                        run_id=run_id,
                        action_id=action.id,
                        event_type="FEASIBILITY_CHECKED",
                        outcome="FRESH_GOOGLE_GET",
                        metadata={
                            "decision": feasibility[0],
                            "reason_codes": (
                                value.get("reason_codes", []) if isinstance(value, dict) else []
                            ),
                            "required_duration": (
                                value.get("required_duration_minutes")
                                if isinstance(value, dict)
                                else None
                            ),
                            "freshness": "FRESH_GOOGLE_GET",
                        },
                        created_at_ms=now_ms,
                    )
                )
            return self._finish(unit_of_work, command=command, now_ms=now_ms, response=response)

    @staticmethod
    def _finish(
        unit_of_work: UnitOfWork,
        *,
        command: ModifyWriteActionCommand,
        now_ms: int,
        response: _ActionMutationResponse,
    ) -> dict[str, object]:
        _finish_json_receipt(
            unit_of_work,
            command.command_id,
            response,
            response.action_version,
            now_ms,
        )
        unit_of_work.commit()
        return cast(dict[str, object], asdict(response))


def _apply_arguments_patch(
    current_arguments: dict[str, object],
    patch: dict[str, object],
) -> dict[str, object]:
    """Merge business-field-only ``patch`` into a write action's arguments.

    Every mutable business field lives under the ``payload`` container that
    CREATE/UPDATE write tools already use; target/container identity fields
    stay outside ``payload`` and are never part of any tool's patchable set,
    so they are always carried through unchanged.
    """

    if not patch:
        return current_arguments
    merged = dict(current_arguments)
    payload = current_arguments.get("payload")
    new_payload = dict(payload) if isinstance(payload, dict) else {}
    new_payload.update(patch)
    merged["payload"] = new_payload
    return merged


def _modify_audit_event(
    *,
    run_id: str,
    action_id: str,
    outcome: str,
    metadata: dict[str, object],
    created_at_ms: int,
    event_type: str = "ACTION_MODIFIED",
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=None,
        run_id=run_id,
        action_id=action_id,
        actor_type="AGENT",
        actor_id="modify_write_action_service",
        actor_display="ModifyWriteActionService",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )


def _revoke_stale_dependent_approvals(
    *,
    unit_of_work: UnitOfWork,
    modified_action_id: str,
    run_id: str,
    command_id: str,
    now_ms: int,
) -> None:
    """Revoke ACTIVE Approvals on direct dependents of a just-modified action.

    08-sequence-design.md requires Modify to trigger a plan/dependency
    re-review; 03-system-architecture.md requires dependent Arguments
    affected by an upstream edit to be re-planned. Neither a Supervisor
    re-review service nor an Action re-planning service exists yet (tracked
    as a follow-on GAP), so this does not attempt either. It only enforces
    the hard safety floor that must hold regardless: an already-APPROVED
    dependent action must never remain executable on an Approval issued
    before its upstream action changed. The dependent's own status/version
    is intentionally left untouched -- there is no Domain command yet for
    "APPROVED action needs a fresh look without content changing" (the same
    gap blocking `refresh_expired_action`), so cancelling or re-approving it
    is left to the user via the existing CancelPendingAction/PROPOSED path.

    SaveWritePlanService now populates `action_dependencies` for WRITE
    actions (GAP-F3 prerequisite: WRITE Action Dependency Persistence), so
    `list_dependents` returns real edges once a plan with
    `depends_on_action_ids` has been saved.
    """

    for dependent_id in unit_of_work.actions.list_dependents(modified_action_id):
        dependent = unit_of_work.actions.get(dependent_id)
        if dependent is None or dependent.status != ActionStatusV1.APPROVED.value:
            continue
        revoked_ids = revoke_active_approvals(unit_of_work, dependent_id)
        if not revoked_ids:
            continue
        unit_of_work.traces.append(
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
        unit_of_work.audits.append(
            _modify_audit_event(
                run_id=run_id,
                action_id=dependent_id,
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={
                    "command_id": command_id,
                    "modified_action_id": modified_action_id,
                    "revoked_approval_ids": list(revoked_ids),
                },
                created_at_ms=now_ms,
                event_type="ACTION_DEPENDENT_APPROVAL_REVOKED",
            )
        )


def _reject_audit_event(
    *,
    run_id: str,
    action_id: str,
    actor_account_id: str | None,
    event_type: str,
    metadata: dict[str, object],
    created_at_ms: int,
) -> AuditEventRecord:
    return AuditEventRecord(
        account_id=actor_account_id,
        run_id=run_id,
        action_id=action_id,
        actor_type="USER",
        actor_id=actor_account_id or "unknown_account",
        actor_display=None,
        event_type=event_type,
        outcome=ResultCode.TRANSITION_APPLIED.value,
        metadata_json=dumps(metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )


def _block_rejected_action_dependents(
    *,
    unit_of_work: UnitOfWork,
    rejected_action_id: str,
    run_id: str,
    command_id: str,
    actor_account_id: str | None,
    now_ms: int,
) -> tuple[str, ...]:
    """Block every still-pending transitive dependent in the persisted DAG."""

    blocked_action_ids: list[str] = []
    pending = list(unit_of_work.actions.list_dependents(rejected_action_id))
    visited: set[str] = set()
    while pending:
        dependent_id = pending.pop(0)
        if dependent_id in visited:
            continue
        visited.add(dependent_id)
        dependent = unit_of_work.actions.get(dependent_id)
        if dependent is None or dependent.status not in {
            ActionStatusV1.PROPOSED.value,
            ActionStatusV1.MODIFIED.value,
            ActionStatusV1.APPROVED.value,
        }:
            continue
        revoked_ids = revoke_active_approvals(unit_of_work, dependent_id)
        if (
            update_action_record(
                unit_of_work,
                dependent_id,
                expected_version=dependent.version,
                expected_status=ActionStatusV1(dependent.status),
                next_status=ActionStatusV1.DEPENDENCY_BLOCKED,
                updated_at_ms=now_ms,
            )
            is None
        ):
            raise RuntimeError(f"dependency block transition failed: {dependent_id}")
        blocked_action_ids.append(dependent_id)
        metadata: dict[str, object] = {
            "command_id": command_id,
            "blocked_by_action_id": rejected_action_id,
            "previous_status": dependent.status,
            "new_status": ActionStatusV1.DEPENDENCY_BLOCKED.value,
            "revoked_approval_ids": list(revoked_ids),
        }
        unit_of_work.traces.append(
            TraceEventRecord(
                run_id=run_id,
                action_id=dependent_id,
                event_type="ACTION_DEPENDENCY_BLOCKED",
                status=ActionStatusV1.DEPENDENCY_BLOCKED.value,
                duration_ms=None,
                payload_json=dumps(
                    {
                        "command_id": command_id,
                        "blocked_by_action_id": rejected_action_id,
                    },
                    sort_keys=True,
                ),
                created_at_ms=now_ms,
            )
        )
        unit_of_work.audits.append(
            _reject_audit_event(
                run_id=run_id,
                action_id=dependent_id,
                actor_account_id=actor_account_id,
                event_type="ACTION_DEPENDENCY_BLOCKED",
                metadata=metadata,
                created_at_ms=now_ms,
            )
        )
        pending.extend(unit_of_work.actions.list_dependents(dependent_id))
    return tuple(blocked_action_ids)


class RejectWriteActionService:
    """Expose the domain reject transition for existing write actions."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RejectWriteActionCommand) -> dict[str, object]:
        if (
            command.reason_code is not None
            and fullmatch(r"[A-Z][A-Z0-9_]{0,127}", command.reason_code) is None
        ):
            raise ValueError("reason_code must be a safe uppercase identifier")
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return cast(
                    dict[str, object],
                    asdict(
                        cast(
                            _ActionMutationResponse,
                            _resolve_existing_receipt(
                                unit_of_work=unit_of_work,
                                receipt=existing,
                                request_hash=command.request_hash,
                                response_type=_ActionMutationResponse,
                                action_id=command.action_id,
                                now_ms=self._now_ms(),
                            ),
                        )
                    ),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RejectWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            plan = unit_of_work.plans.load_bundle(action.plan_id)
            if plan is None:
                raise LookupError(f"plan not found: {action.plan_id}")
            run = unit_of_work.runs.get(plan.run_id)
            if run is None:
                raise LookupError(f"run not found: {plan.run_id}")
            current_plan = max(
                current_plan_tuple(unit_of_work.plans, plan.run_id),
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            preview = transition_reject_action(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            revoked_approval_ids: tuple[str, ...] = ()
            if preview.applied:
                revoked_approval_ids = revoke_active_approvals(unit_of_work, action.id)
                if (
                    update_action_record(
                        unit_of_work,
                        action.id,
                        expected_version=action.version,
                        expected_status=ActionStatusV1(action.status),
                        next_status=preview.current_status,
                        updated_at_ms=now_ms,
                    )
                    is None
                ):
                    raise RuntimeError("validated RejectAction CAS failed")
            result = preview
            response = _ActionMutationResponse(
                applied=result.applied,
                result_code=result.result_code.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(
                    item.value
                    for item in next_allowed_action_commands(
                        result.current_status,
                        effect_type=EffectType(action.effect_type),
                    )
                ),
                conflict_detail=result.conflict_detail,
            )
            if result.applied:
                blocked_action_ids = _block_rejected_action_dependents(
                    unit_of_work=unit_of_work,
                    rejected_action_id=action.id,
                    run_id=run.id,
                    command_id=command.command_id,
                    actor_account_id=command.actor_account_id,
                    now_ms=now_ms,
                )
                audit_metadata: dict[str, object] = {
                    "plan_id": plan.id,
                    "action_id": action.id,
                    "command_id": command.command_id,
                    "previous_status": action.status,
                    "new_status": result.current_status.value,
                    "reason_present": command.reason_code is not None,
                    "revoked_approval_ids": list(revoked_approval_ids),
                    "blocked_dependent_action_ids": list(blocked_action_ids),
                }
                if command.reason_code is not None:
                    audit_metadata["reason_code"] = command.reason_code
                unit_of_work.traces.append(
                    TraceEventRecord(
                        run_id=run.id,
                        action_id=action.id,
                        event_type="ACTION_REJECTED",
                        status=result.current_status.value,
                        duration_ms=None,
                        payload_json=dumps({"command_id": command.command_id}, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.append(
                    _reject_audit_event(
                        run_id=run.id,
                        action_id=action.id,
                        actor_account_id=command.actor_account_id,
                        event_type="ACTION_REJECTED",
                        metadata=audit_metadata,
                        created_at_ms=now_ms,
                    )
                )
                current_actions = unit_of_work.actions.list_for_plan(plan.id)
                terminal_statuses = {
                    ActionStatusV1.REJECTED.value,
                    ActionStatusV1.VERIFIED.value,
                    ActionStatusV1.FAILED.value,
                    ActionStatusV1.BLOCKED.value,
                    ActionStatusV1.DEPENDENCY_BLOCKED.value,
                    ActionStatusV1.MISMATCH.value,
                    ActionStatusV1.CANCELLED.value,
                }
                if current_actions and all(
                    item.status in terminal_statuses for item in current_actions
                ):
                    verifying_status = transition_begin_verification(run.status)
                    if not unit_of_work.runs.update_if_version_and_status(
                        run.id,
                        run.version,
                        frozenset({run.status}),
                        {"status": verifying_status.value, "version": run.version + 1},
                    ):
                        raise RuntimeError("validated BeginVerification CAS failed")
                    completed_status = transition_complete_write_run(verifying_status)
                    if not unit_of_work.runs.update_if_version_and_status(
                        run.id,
                        run.version + 1,
                        frozenset({verifying_status}),
                        {
                            "status": completed_status.value,
                            "version": run.version + 2,
                            "finished_at_ms": now_ms,
                        },
                    ):
                        raise RuntimeError("validated CompleteWriteRun CAS failed")
                    if plan.status in {
                        PlanStatusV1.WAITING_APPROVAL,
                        PlanStatusV1.ACTIVE,
                    } and (
                        update_plan_record(
                            unit_of_work,
                            plan.id,
                            expected_status=plan.status,
                            next_status=PlanStatusV1.COMPLETED,
                        )
                        is None
                    ):
                        raise RuntimeError(f"validated Plan completion CAS failed: {plan.id}")
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                response.action_version,
                now_ms,
            )
            unit_of_work.commit()
            return cast(dict[str, object], asdict(response))


def _mutate_write_action(
    *,
    unit_of_work_factory: Callable[[], UnitOfWork],
    now_ms: Callable[[], int],
    command_id: str,
    request_hash: str,
    action_id: str,
    expected_version: int,
    command_type: str,
    transition_name: str,
    mutate: Callable[[UnitOfWork, int], CommandResult[ActionStatusV1, ActionCommand]],
) -> dict[str, object]:
    with unit_of_work_factory() as unit_of_work:
        existing = unit_of_work.command_receipts.get_by_command_id(command_id)
        if existing is not None:
            return cast(
                dict[str, object],
                asdict(
                    cast(
                        _ActionMutationResponse,
                        _resolve_existing_receipt(
                            unit_of_work=unit_of_work,
                            receipt=existing,
                            request_hash=request_hash,
                            response_type=_ActionMutationResponse,
                            action_id=action_id,
                            now_ms=now_ms(),
                        ),
                    )
                ),
            )

        updated_at_ms = now_ms()
        unit_of_work.command_receipts.reserve_or_replay(
            command_id=command_id,
            command_type=command_type,
            request_hash=request_hash,
            aggregate_type="Action",
            aggregate_id=action_id,
            created_at_ms=updated_at_ms,
        )
        action = _require_action(unit_of_work, action_id)
        result = mutate(unit_of_work, updated_at_ms)
        response = _ActionMutationResponse(
            applied=result.applied,
            result_code=result.result_code.value,
            action_id=action.id,
            action_status=result.current_status.value,
            action_version=result.current_version,
            next_allowed_commands=tuple(
                item.value
                for item in next_allowed_action_commands(
                    result.current_status,
                    effect_type=EffectType(action.effect_type),
                )
            ),
            conflict_detail=result.conflict_detail,
        )
        if result.applied:
            run_id = _run_id_for_action(unit_of_work, action_id)
            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=run_id,
                    action_id=action_id,
                    event_type=transition_name,
                    status=result.current_status.value,
                    duration_ms=None,
                    payload_json=dumps({"command_id": command_id}, sort_keys=True),
                    created_at_ms=updated_at_ms,
                )
            )
        _finish_json_receipt(
            unit_of_work,
            command_id,
            response,
            response.action_version,
            updated_at_ms,
        )
        unit_of_work.commit()
        return cast(dict[str, object], asdict(response))


def _run_id_for_action(unit_of_work: UnitOfWork, action_id: str) -> str:
    action = _require_action(unit_of_work, action_id)
    plan = unit_of_work.plans.load_bundle(action.plan_id)
    if plan is None:
        raise LookupError(f"plan not found for action: {action_id}")
    return plan.run_id


def _require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
    action = unit_of_work.actions.get(action_id)
    if action is None:
        raise LookupError(f"action not found: {action_id}")
    return action
