"""Approval use case for write actions."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.policy_kernels.calendar_conflict import CalendarConflictDecision
from google_work_agent.application.tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.action.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_source_snapshot_for_calendar_conflict,
    calendar_conflict_authority,
    require_calendar_conflict_acknowledgement,
)
from google_work_agent.application.use_cases.action.feasibility import (
    approval_source_snapshot_for_feasibility,
    feasibility_authority,
    require_feasibility_approval,
)
from google_work_agent.application.use_cases.action.persistence_cas import update_action_record
from google_work_agent.application.use_cases.action.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_source_snapshot_for_task_duplicate,
    duplicate_authority,
    require_duplicate_acknowledgement,
)
from google_work_agent.application.use_cases.action.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    action_response_from_result as _action_response_from_result,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    resolve_existing_action_receipt as _resolve_existing_action_receipt,
)
from google_work_agent.application.use_cases.claim.write_execution_integrity import (
    calculate_recovery_fingerprint,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.domain.action.model import (
    ActionStatusV1,
    EffectType,
    PolicyViolationError,
    next_allowed_action_commands,
)
from google_work_agent.domain.action.transitions.approve_action import transition_approve_action
from google_work_agent.domain.approval.model import Approval as ApprovalRecord
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.canonical import (
    calculate_canonical_json_hash,
    canonicalize_json_value,
)
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.approval_repository import active_approval_tuple
from google_work_agent.ports.persistence.plan_repository import current_plan_tuple
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class ApproveWriteActionService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._registry = load_signed_tool_registry()

    def __call__(self, command: ApproveWriteActionCommand) -> WriteActionResponse:
        if command.ttl_ms <= 0:
            raise ValueError("approval ttl must be positive")
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    now_ms=self._now_ms(),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="ApproveWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            entry = self._registry.get_required("google_workspace", action.tool_name)
            plan = _require_plan(unit_of_work, action.plan_id)
            run = _require_run(unit_of_work, plan.run_id)
            plans = tuple(current_plan_tuple(unit_of_work.plans, run.id))
            current_plan = max(
                plans,
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            if (
                plan.status is not PlanStatusV1.WAITING_APPROVAL
                or current_plan is None
                or current_plan.id != plan.id
                or run.status is not RunStatusV1.WAITING_APPROVAL
            ):
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="approval requires the current published Plan and parent Run",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            if plan.review_status is not PlanReviewStatus.PASSED:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="plan review must pass after the latest action modification",
                )
                unit_of_work.audits.append(
                    _audit_event(
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
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            approval_source_snapshot = command.source_snapshot
            duplicate_decision = None
            calendar_decision = None
            if action.tool_name == TASK_CREATE_TOOL and action.version == command.expected_version:
                try:
                    duplicate_decision = require_duplicate_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.duplicate_acknowledged,
                    )
                except PolicyViolationError as error:
                    plan = _require_plan(unit_of_work, action.plan_id)
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status),
                                effect_type=EffectType(action.effect_type),
                            )
                        ),
                        conflict_detail=str(error),
                    )
                    unit_of_work.audits.append(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="TASK_DUPLICATE_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                "decision": (duplicate_authority(action.risk) or ("UNKNOWN", ()))[
                                    0
                                ],
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    _finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        response,
                        action.version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return response
                approval_source_snapshot = {
                    **command.source_snapshot,
                    **approval_source_snapshot_for_task_duplicate(
                        risk=action.risk,
                        acknowledged=command.duplicate_acknowledged,
                    ),
                }
            if (
                action.tool_name in CALENDAR_CONFLICT_TOOLS
                and action.version == command.expected_version
            ):
                try:
                    require_feasibility_approval(action.risk)
                except PolicyViolationError as error:
                    plan = _require_plan(unit_of_work, action.plan_id)
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status),
                                effect_type=EffectType(action.effect_type),
                            )
                        ),
                        conflict_detail=str(error),
                    )
                    unit_of_work.audits.append(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="FEASIBILITY_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                **feasibility_audit_metadata(action.risk),
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                try:
                    calendar_decision = require_calendar_conflict_acknowledgement(
                        risk=action.risk,
                        acknowledged=command.calendar_conflict_acknowledged,
                    )
                except PolicyViolationError as error:
                    plan = _require_plan(unit_of_work, action.plan_id)
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=tuple(
                            item.value
                            for item in next_allowed_action_commands(
                                ActionStatusV1(action.status),
                                effect_type=EffectType(action.effect_type),
                            )
                        ),
                        conflict_detail=str(error),
                    )
                    unit_of_work.audits.append(
                        _audit_event(
                            run_id=plan.run_id,
                            action_id=action.id,
                            event_type="CALENDAR_CONFLICT_APPROVAL_BLOCKED",
                            outcome=ResultCode.STATE_CONFLICT.value,
                            metadata={
                                "command_id": command.command_id,
                                **calendar_conflict_audit_metadata(
                                    risk=action.risk, action_id=action.id
                                ),
                            },
                            created_at_ms=now_ms,
                        )
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                approval_source_snapshot = {
                    **approval_source_snapshot,
                    **approval_source_snapshot_for_calendar_conflict(
                        risk=action.risk,
                        acknowledged=command.calendar_conflict_acknowledged,
                    ),
                    **approval_source_snapshot_for_feasibility(risk=action.risk),
                }
            approval_result = transition_approve_action(
                ActionStatusV1(action.status),
                action.version,
                command.expected_version,
                effect_type=EffectType(action.effect_type),
                plan_review_passed=plan.review_status is PlanReviewStatus.PASSED,
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            if not approval_result.applied:
                response = _action_response_from_result(
                    action_id=action.id,
                    result=approval_result,
                )
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response
            if (
                update_action_record(
                    unit_of_work,
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=approval_result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ApproveAction CAS failed")

            approval = ApprovalRecord(
                id=command.approval_id,
                action_id=action.id,
                approval_no=len(active_approval_tuple(unit_of_work.approvals, action.id)) + 1,
                action_version=approval_result.current_version,
                status=ApprovalStatusV1.ACTIVE,
                approved_by_account_id=command.approved_by_account_id,
                approved_by_display=command.approved_by_display,
                arguments_snapshot_json=action.arguments_json,
                canonical_arguments_hash=action.arguments_hash,
                source_snapshot_json=canonicalize_json_value(approval_source_snapshot),
                source_snapshot_hash=calculate_canonical_json_hash(approval_source_snapshot),
                policy_version=entry.registry_version,
                tool_schema_version=entry.input_schema_version,
                idempotency_key=command.idempotency_key,
                recovery_fingerprint=calculate_recovery_fingerprint(
                    tool_name=action.tool_name,
                    arguments_hash=action.arguments_hash,
                    source_snapshot_hash=calculate_canonical_json_hash(approval_source_snapshot),
                ),
                approved_at_ms=now_ms,
                expires_at_ms=now_ms + command.ttl_ms,
                consumed_at_ms=None,
            )
            unit_of_work.approvals.insert_active_snapshot(approval)

            plan = _require_plan(unit_of_work, action.plan_id)
            # Write Plans remain WAITING_APPROVAL while approved Actions execute.

            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_APPROVED",
                    status=ActionStatusV1.APPROVED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "command_id": command.command_id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
                _audit_event(
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
                unit_of_work.audits.append(
                    _audit_event(
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
                unit_of_work.audits.append(
                    _audit_event(
                        run_id=plan.run_id,
                        action_id=action.id,
                        event_type="CALENDAR_CONFLICT_OVERRIDE_ACKNOWLEDGED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata={
                            "approval_id": approval.id,
                            **calendar_conflict_audit_metadata(
                                risk=action.risk, action_id=action.id
                            ),
                        },
                        created_at_ms=now_ms,
                    )
                )
            response = WriteActionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=approval_result.current_status.value,
                action_version=approval_result.current_version,
                next_allowed_commands=tuple(
                    item.value for item in approval_result.next_allowed_commands
                ),
                approval_id=approval.id,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                approval_result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


def calendar_conflict_audit_metadata(
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


def feasibility_audit_metadata(risk: dict[str, object]) -> dict[str, object]:
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
