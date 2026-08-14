"""Claim validation and durable claim issuance for write actions."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads

from google_work_agent.application.calendar_conflicts import (
    CALENDAR_CONFLICT_TOOLS,
    approval_calendar_conflict_authority,
    calendar_conflict_authority,
    calendar_conflict_change_requires_reapproval,
)
from google_work_agent.application.feasibility import (
    approval_feasibility_authority,
    feasibility_authority,
    feasibility_change_requires_reapproval,
)
from google_work_agent.application.task_duplicates import (
    TASK_CREATE_TOOL,
    approval_duplicate_authority,
    duplicate_authority,
    duplicate_change_requires_reapproval,
)
from google_work_agent.application.write_action_arguments import dict_argument as _dict_argument
from google_work_agent.application.write_approval_contracts import DEFAULT_APPROVAL_TTL_MS
from google_work_agent.application.write_execution_contracts import (
    ClaimWriteActionCommand,
    WriteActionResponse,
)
from google_work_agent.application.write_execution_integrity import (
    CLAIM_TOKEN_VERSION,
    issue_claim_token,
)
from google_work_agent.application.write_persistence import (
    action_response_from_result as _action_response_from_result,
)
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.write_persistence import (
    resolve_existing_action_receipt as _resolve_existing_action_receipt,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    ApprovalIntegrityInput,
    EffectType,
    ExecutionAttemptStatus,
    PolicyViolationError,
    ResultCode,
    RunStatus,
    build_p0_tool_registry,
    calculate_canonical_json_hash,
    transition_action,
    validate_approval_integrity,
)
from google_work_agent.ports import ExecutionAttemptRecord, TraceEventRecord, UnitOfWork


class ClaimWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        signing_secret: str,
        service_instance_id: str,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._signing_secret = signing_secret
        self._service_instance_id = service_instance_id
        self._registry = build_p0_tool_registry()

    def __call__(self, command: ClaimWriteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ClaimWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            run = _require_run(unit_of_work, plan.run_id)
            if run.status in {
                RunStatus.CANCEL_REQUESTED,
                RunStatus.CANCELLED,
                RunStatus.RECOVERY_REQUIRED,
            }:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="run status forbids a new write claim",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            approval = unit_of_work.approvals.get_active_by_action(action.id)
            if approval is None:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="write action requires an active approval",
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

            entry = self._registry.require(action.tool_name)
            current_source_snapshot = command.source_snapshot
            if action.tool_name == TASK_CREATE_TOOL:
                stored_approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
                if duplicate_change_requires_reapproval(
                    approved=approval_duplicate_authority(stored_approval_snapshot),
                    current=duplicate_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="task duplicate risk changed after approval",
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
                # Task duplicate authority is server-owned. Claim never
                # accepts a client projection in place of the Approval snapshot.
                task_duplicate_snapshot = stored_approval_snapshot.get("task_duplicate")
                current_source_snapshot = {
                    **command.source_snapshot,
                    "task_duplicate": task_duplicate_snapshot,
                }
            if action.tool_name in CALENDAR_CONFLICT_TOOLS:
                stored_approval_snapshot = _dict_argument(loads(approval.source_snapshot_json))
                if feasibility_change_requires_reapproval(
                    approved=approval_feasibility_authority(stored_approval_snapshot),
                    current=feasibility_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="feasibility risk changed after approval",
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, action.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                if calendar_conflict_change_requires_reapproval(
                    approved=approval_calendar_conflict_authority(stored_approval_snapshot),
                    current=calendar_conflict_authority(action.risk),
                ):
                    response = WriteActionResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        action_id=action.id,
                        action_status=action.status,
                        action_version=action.version,
                        next_allowed_commands=(),
                        conflict_detail="calendar conflict risk changed after approval",
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
                current_source_snapshot = {
                    **command.source_snapshot,
                    "calendar_conflict": stored_approval_snapshot.get("calendar_conflict"),
                    "feasibility": stored_approval_snapshot.get("feasibility"),
                }
            try:
                validate_approval_integrity(
                    ApprovalIntegrityInput(
                        approval_arguments_hash=approval.canonical_arguments_hash,
                        current_arguments_hash=action.arguments_hash,
                        approval_source_snapshot_hash=approval.source_snapshot_hash,
                        current_source_snapshot_hash=calculate_canonical_json_hash(
                            current_source_snapshot
                        ),
                        approval_action_version=approval.action_version,
                        current_action_version=action.version,
                        approval_policy_version=approval.policy_version,
                        current_policy_version=entry.registry_version,
                        approval_tool_schema_version=approval.tool_schema_version,
                        current_tool_schema_version=entry.input_schema_version,
                        now_ms=now_ms,
                        expires_at_ms=approval.expires_at_ms,
                    )
                )
            except PolicyViolationError as error:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail=str(error),
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
            if unit_of_work.execution_attempts.get_active_by_approval(approval.id) is not None:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    conflict_detail="write action already has an active execution attempt",
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

            preview = transition_action(
                ActionStatus(action.status),
                command=ActionCommand.CLAIM_EXECUTION,
                current_version=action.version,
                expected_version=command.expected_version,
                effect_type=EffectType(action.effect_type),
            )
            if not preview.applied:
                response = _action_response_from_result(action_id=action.id, result=preview)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    action.version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

            unit_of_work.approvals.mark_consumed(approval.id, consumed_at_ms=now_ms)
            result = unit_of_work.actions.claim_execution(
                action.id,
                expected_version=command.expected_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError("validated write claim transition was not applied")

            attempt = ExecutionAttemptRecord(
                id=command.attempt_id,
                approval_id=approval.id,
                attempt_no=len(unit_of_work.execution_attempts.list_by_approval(approval.id)) + 1,
                status=ExecutionAttemptStatus.CLAIMED,
                version=0,
                result_resource_ref_id=None,
                response_metadata_json=None,
                error_code=None,
                error_detail_json=None,
                started_at_ms=now_ms,
                finished_at_ms=None,
            )
            unit_of_work.execution_attempts.insert_claimed(attempt)
            claim_token = issue_claim_token(
                {
                    "version": CLAIM_TOKEN_VERSION,
                    "action_id": action.id,
                    "approval_id": approval.id,
                    "attempt_id": attempt.id,
                    "tool_name": action.tool_name,
                    "arguments_hash": action.arguments_hash,
                    "service_instance_id": self._service_instance_id,
                    "nonce": command.nonce,
                    "issued_at_ms": now_ms,
                    "expires_at_ms": now_ms + DEFAULT_APPROVAL_TTL_MS,
                },
                signing_secret=self._signing_secret,
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_CLAIMED",
                    status=ActionStatus.EXECUTING.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"approval_id": approval.id, "attempt_id": attempt.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_CLAIMED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"approval_id": approval.id, "attempt_id": attempt.id},
                    created_at_ms=now_ms,
                )
            )
            response = WriteActionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=result.current_status.value,
                action_version=result.current_version,
                next_allowed_commands=tuple(item.value for item in result.next_allowed_commands),
                approval_id=approval.id,
                attempt_id=attempt.id,
                claim_token=claim_token,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                result.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return response
