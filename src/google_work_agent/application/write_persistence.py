"""Persistence primitives shared by write application services."""

from __future__ import annotations

from dataclasses import asdict
from json import dumps, loads
from typing import cast

from google_work_agent.ports.observability_events import sanitize_event_attributes
from google_work_agent.application.write_execution_contracts import WriteActionResponse, WriteRunResponse
from google_work_agent.application.write_plan_contracts import (
    PublishWritePlanResponse,
    SaveWritePlanResponse,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    CommandResult,
    EffectType,
    ResultCode,
    RunStatus,
    next_allowed_action_commands,
)
from google_work_agent.ports import (
    ActionRecord,
    ApprovalRecord,
    AuditEventRecord,
    CommandReceiptRecord,
    CommandReceiptStatus,
    ExecutionAttemptRecord,
    PlanRecord,
    ResourceRefRecord,
    RunRecord,
    TraceEventRecord,
    UnitOfWork,
)

WriteResponse = SaveWritePlanResponse | PublishWritePlanResponse | WriteActionResponse | WriteRunResponse
WriteResponseType = (
    type[SaveWritePlanResponse]
    | type[PublishWritePlanResponse]
    | type[WriteActionResponse]
    | type[WriteRunResponse]
)


def resolve_json_receipt(
    *, receipt: CommandReceiptRecord, request_hash: str, response_type: WriteResponseType
) -> WriteResponse:
    if receipt.request_hash != request_hash:
        if response_type is WriteActionResponse:
            return WriteActionResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                action_id=receipt.aggregate_id or "",
                action_status="UNKNOWN",
                action_version=receipt.result_version or 0,
                next_allowed_commands=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is SaveWritePlanResponse:
            return SaveWritePlanResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                plan_id=receipt.aggregate_id or "",
                plan_status="UNKNOWN",
                action_ids=(),
                conflict_detail="command_id already exists with a different request_hash",
            )
        if response_type is WriteRunResponse:
            return WriteRunResponse(
                applied=False,
                result_code=ResultCode.DUPLICATE_COMMAND.value,
                run_id=receipt.aggregate_id or "",
                run_status="UNKNOWN",
                run_version=receipt.result_version or 0,
                plan_id=None,
                plan_status=None,
                conflict_detail="command_id already exists with a different request_hash",
            )
        return PublishWritePlanResponse(
            applied=False,
            result_code=ResultCode.DUPLICATE_COMMAND.value,
            run_status="UNKNOWN",
            run_version=receipt.result_version or 0,
            plan_id=receipt.aggregate_id or "",
            plan_status="UNKNOWN",
            conflict_detail="command_id already exists with a different request_hash",
        )
    if receipt.response_json is None or receipt.status is CommandReceiptStatus.RECEIVED:
        raise RuntimeError("RECEIVED receipt recovery requires aggregate-specific handling")
    payload = loads(receipt.response_json)
    if "next_allowed_commands" in payload:
        payload["next_allowed_commands"] = tuple(payload["next_allowed_commands"])
    if "action_ids" in payload:
        payload["action_ids"] = tuple(payload["action_ids"])
    return response_type(**payload)


def finish_json_receipt(
    unit_of_work: UnitOfWork,
    command_id: str,
    response: WriteResponse,
    result_version: int,
    completed_at_ms: int,
) -> None:
    unit_of_work.command_receipts.finish_json(
        command_id=command_id,
        applied=bool(response.applied),
        result_code=ResultCode(str(response.result_code)),
        result_version=result_version,
        response_json=dumps(asdict(response), sort_keys=True),
        completed_at_ms=completed_at_ms,
    )


def require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get_by_id(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run


def require_plan(unit_of_work: UnitOfWork, plan_id: str) -> PlanRecord:
    plan = unit_of_work.plans.get_by_id(plan_id)
    if plan is None:
        raise LookupError(f"plan not found: {plan_id}")
    return plan


def require_latest_plan_for_run(unit_of_work: UnitOfWork, run_id: str) -> PlanRecord:
    plans = unit_of_work.plans.list_by_run(run_id)
    if not plans:
        raise LookupError(f"plan not found for run: {run_id}")
    return plans[-1]


def require_action(unit_of_work: UnitOfWork, action_id: str) -> ActionRecord:
    action = unit_of_work.actions.get_by_id(action_id)
    if action is None:
        raise LookupError(f"action not found: {action_id}")
    return action


def require_approval(unit_of_work: UnitOfWork, approval_id: str) -> ApprovalRecord:
    approval = unit_of_work.approvals.get_by_id(approval_id)
    if approval is None:
        raise LookupError(f"approval not found: {approval_id}")
    return approval


def require_attempt(unit_of_work: UnitOfWork, attempt_id: str) -> ExecutionAttemptRecord:
    attempt = unit_of_work.execution_attempts.get_by_id(attempt_id)
    if attempt is None:
        raise LookupError(f"execution attempt not found: {attempt_id}")
    return attempt


def audit_event(
    *,
    run_id: str,
    action_id: str | None,
    event_type: str,
    outcome: str,
    metadata: dict[str, object],
    created_at_ms: int,
) -> AuditEventRecord:
    sanitized_metadata = sanitize_event_attributes(metadata).values
    return AuditEventRecord(
        account_id=None,
        run_id=run_id,
        action_id=action_id,
        actor_type="AGENT",
        actor_id="write_action_service",
        actor_display="WriteActionService",
        event_type=event_type,
        outcome=outcome,
        metadata_json=dumps(sanitized_metadata, sort_keys=True),
        created_at_ms=created_at_ms,
    )


def emit_command_rejected_hash_mismatch(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    run_id: str | None,
    action_id: str | None,
    now_ms: int,
) -> None:
    metadata: dict[str, object] = {
        "command_id": receipt.command_id,
        "command_type": receipt.command_type,
        "result_code": ResultCode.DUPLICATE_COMMAND.value,
    }
    sanitized_metadata = sanitize_event_attributes(metadata).values
    unit_of_work.audits.add(
        AuditEventRecord(
            account_id=None,
            run_id=run_id,
            action_id=action_id,
            actor_type="SYSTEM",
            actor_id="command_receipt",
            actor_display="CommandReceipt",
            event_type="COMMAND_REJECTED_HASH_MISMATCH",
            outcome=ResultCode.DUPLICATE_COMMAND.value,
            metadata_json=dumps(sanitized_metadata, sort_keys=True),
            created_at_ms=now_ms,
        )
    )
    if run_id is not None:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id=run_id,
                action_id=action_id,
                event_type="COMMAND_REJECTED_HASH_MISMATCH",
                status=ResultCode.DUPLICATE_COMMAND.value,
                duration_ms=None,
                payload_json=dumps(sanitized_metadata, sort_keys=True),
                created_at_ms=now_ms,
            )
        )
    unit_of_work.commit()


def cancel_pending_actions(
    *, unit_of_work: UnitOfWork, run_id: str, plan_id: str, updated_at_ms: int
) -> None:
    pending_statuses = {
        ActionStatus.PROPOSED.value,
        ActionStatus.MODIFIED.value,
        ActionStatus.APPROVED.value,
        ActionStatus.EXPIRED.value,
    }
    for action in unit_of_work.actions.list_by_plan(plan_id):
        if action.status not in pending_statuses:
            continue
        if action.status == ActionStatus.APPROVED.value:
            unit_of_work.approvals.revoke_active_by_action(action.id)
        result = unit_of_work.actions.cancel_pending(
            action.id, expected_version=action.version, updated_at_ms=updated_at_ms
        )
        if not result.applied:
            raise RuntimeError(f"pending action cancellation failed: {action.id}")
        unit_of_work.audits.add(
            audit_event(
                run_id=run_id,
                action_id=action.id,
                event_type="ACTION_CANCELLED",
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={
                    "plan_id": plan_id,
                    "previous_status": action.status,
                    "new_status": ActionStatus.CANCELLED.value,
                },
                created_at_ms=updated_at_ms,
            )
        )


def resolve_existing_run_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    run_id: str,
    now_ms: int,
) -> WriteRunResponse:
    if receipt.request_hash != request_hash:
        emit_command_rejected_hash_mismatch(
            unit_of_work=unit_of_work,
            receipt=receipt,
            run_id=run_id,
            action_id=None,
            now_ms=now_ms,
        )
        return cast(
            WriteRunResponse,
            resolve_json_receipt(
                receipt=receipt, request_hash=request_hash, response_type=WriteRunResponse
            ),
        )
    if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
        run = require_run(unit_of_work, run_id)
        plans = unit_of_work.plans.list_by_run(run_id)
        plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
        applied_statuses = (
            {RunStatus.COMPLETED.value, RunStatus.PLANNING.value}
            if receipt.command_type == "ResolveMismatchRecovery"
            else {
                RunStatus.CANCEL_REQUESTED.value,
                RunStatus.CANCELLED.value,
                RunStatus.REAUTH_REQUIRED.value,
                RunStatus.RECOVERY_REQUIRED.value,
                RunStatus.VERIFYING.value,
            }
        )
        return WriteRunResponse(
            applied=run.status.value in applied_statuses,
            result_code=(
                ResultCode.TRANSITION_APPLIED.value
                if run.status.value in applied_statuses
                else ResultCode.RECOVERY_REQUIRED.value
            ),
            run_id=run.id,
            run_status=run.status.value,
            run_version=run.version,
            plan_id=None if plan is None else plan.id,
            plan_status=None if plan is None else plan.status.value,
            result_kind=run.status.value,
            conflict_detail=None
            if run.status.value in applied_statuses
            else "receipt exists in RECEIVED state; aggregate recovery is inconclusive",
        )
    return cast(
        WriteRunResponse,
        resolve_json_receipt(
            receipt=receipt, request_hash=request_hash, response_type=WriteRunResponse
        ),
    )


def resolve_snapshot_fallback_resource_id(
    unit_of_work: UnitOfWork,
    *,
    action: ActionRecord,
    resource_ref_id: str | None,
) -> str | None:
    arguments = loads(action.arguments_json)
    if action.tool_name in {"gmail_create_draft", "gmail_update_draft"}:
        return None if arguments.get("draft_id") is not None else resource_id_from_ref(unit_of_work, resource_ref_id)
    if action.tool_name in {"tasks_create_task", "tasks_update_task"}:
        return None if arguments.get("task_id") is not None else resource_id_from_ref(unit_of_work, resource_ref_id)
    if action.tool_name in {"calendar_create_event", "calendar_update_event"}:
        return None if arguments.get("event_id") is not None else resource_id_from_ref(unit_of_work, resource_ref_id)
    if action.tool_name == "gmail_send":
        return resource_id_from_ref(unit_of_work, resource_ref_id)
    return None


def resource_id_from_ref(unit_of_work: UnitOfWork, resource_ref_id: str | None) -> str:
    if resource_ref_id is None:
        raise LookupError("result_resource_ref_id is required for verification")
    resource_ref = unit_of_work.resource_refs.get_by_id(resource_ref_id)
    if resource_ref is None:
        raise LookupError(f"resource ref not found: {resource_ref_id}")
    return resource_ref.resource_id


def upsert_resource_ref(
    *, unit_of_work: UnitOfWork, resource_ref: ResourceRefRecord
) -> ResourceRefRecord:
    """Persist by the single connector-aware ResourceRef identity."""
    if not resource_ref.connector_id:
        raise ValueError("resource reference connector_id is required")
    unit_of_work.resource_refs.upsert(resource_ref)
    persisted = unit_of_work.resource_refs.get_by_unique_key(
        run_id=resource_ref.run_id,
        connector_id=resource_ref.connector_id,
        resource_type=resource_ref.resource_type.value,
        resource_id=resource_ref.resource_id,
    )
    if persisted is None:
        raise RuntimeError("resource reference upsert did not persist")
    return persisted


def action_response_from_result(
    *, action_id: str, result: CommandResult[ActionStatus, ActionCommand]
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=result.applied,
        result_code=result.result_code.value,
        action_id=action_id,
        action_status=result.current_status.value,
        action_version=result.current_version,
        next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
        conflict_detail=result.conflict_detail,
    )


def write_action_version_conflict_response(
    *, action: ActionRecord, attempt_id: str, conflict_detail: str
) -> WriteActionResponse:
    return WriteActionResponse(
        applied=False,
        result_code=ResultCode.VERSION_CONFLICT.value,
        action_id=action.id,
        action_status=action.status,
        action_version=action.version,
        next_allowed_commands=tuple(
            item.value for item in next_allowed_write_commands_for_record(action)
        ),
        attempt_id=attempt_id,
        conflict_detail=conflict_detail,
    )


def resolve_existing_action_receipt(
    *,
    unit_of_work: UnitOfWork,
    receipt: CommandReceiptRecord,
    request_hash: str,
    action_id: str,
    now_ms: int,
) -> WriteActionResponse:
    if receipt.request_hash != request_hash:
        emit_command_rejected_hash_mismatch(
            unit_of_work=unit_of_work,
            receipt=receipt,
            run_id=None,
            action_id=action_id,
            now_ms=now_ms,
        )
        return cast(
            WriteActionResponse,
            resolve_json_receipt(
                receipt=receipt, request_hash=request_hash, response_type=WriteActionResponse
            ),
        )
    if receipt.status is CommandReceiptStatus.RECEIVED or receipt.response_json is None:
        action = require_action(unit_of_work, action_id)
        applied_statuses = {
            ActionStatus.FAILED.value,
            ActionStatus.UNKNOWN_RESULT.value,
            ActionStatus.EXECUTED.value,
            ActionStatus.VERIFIED.value,
            ActionStatus.MODIFIED.value,
            ActionStatus.MISMATCH.value,
            ActionStatus.DEPENDENCY_BLOCKED.value,
        }
        return WriteActionResponse(
            applied=action.status in applied_statuses,
            result_code=(
                ResultCode.TRANSITION_APPLIED.value
                if action.status in applied_statuses
                else ResultCode.RECOVERY_REQUIRED.value
            ),
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=tuple(
                item.value for item in next_allowed_write_commands_for_record(action)
            ),
            conflict_detail=None
            if action.status in applied_statuses
            else "receipt exists in RECEIVED state; aggregate recovery is inconclusive",
        )
    return cast(
        WriteActionResponse,
        resolve_json_receipt(
            receipt=receipt, request_hash=request_hash, response_type=WriteActionResponse
        ),
    )


def propagate_dependency_blocked(
    *,
    unit_of_work: UnitOfWork,
    action_id: str,
    run_id: str,
    updated_at_ms: int,
) -> None:
    blocked_action_ids: list[str] = []
    pending = list(unit_of_work.action_dependencies.list_dependents(action_id))
    visited: set[str] = set()
    while pending:
        dependent_action_id = pending.pop(0)
        if dependent_action_id in visited:
            continue
        visited.add(dependent_action_id)
        dependent = unit_of_work.actions.get_by_id(dependent_action_id)
        if dependent is not None and dependent.status in {
            ActionStatus.PROPOSED.value,
            ActionStatus.MODIFIED.value,
            ActionStatus.APPROVED.value,
        }:
            unit_of_work.approvals.revoke_active_by_action(dependent_action_id)
            if not unit_of_work.actions.mark_dependency_blocked(
                dependent_action_id, updated_at_ms=updated_at_ms
            ):
                raise RuntimeError(f"dependency block transition failed: {dependent_action_id}")
            blocked_action_ids.append(dependent_action_id)
            pending.extend(unit_of_work.action_dependencies.list_dependents(dependent_action_id))
    for blocked_action_id in blocked_action_ids:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id=run_id,
                action_id=blocked_action_id,
                event_type="WRITE_DEPENDENCY_BLOCKED",
                status=ActionStatus.DEPENDENCY_BLOCKED.value,
                duration_ms=None,
                payload_json=dumps({"blocked_by_action_id": action_id}, sort_keys=True),
                created_at_ms=updated_at_ms,
            )
        )
        unit_of_work.audits.add(
            audit_event(
                run_id=run_id,
                action_id=blocked_action_id,
                event_type="WRITE_DEPENDENCY_BLOCKED",
                outcome=ResultCode.TRANSITION_APPLIED.value,
                metadata={"blocked_by_action_id": action_id},
                created_at_ms=updated_at_ms,
            )
        )


def next_allowed_write_commands_for_record(action: ActionRecord) -> tuple[ActionCommand, ...]:
    return next_allowed_action_commands(
        ActionStatus(action.status), effect_type=EffectType(action.effect_type)
    )