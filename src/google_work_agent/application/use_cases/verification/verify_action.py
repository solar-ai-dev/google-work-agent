"""Verify one succeeded write by effect-specific connector read and durable comparison."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps, loads

from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
)
from google_work_agent.application.use_cases.verification.normalize_snapshot import normalize_snapshot
from google_work_agent.application.write_action_arguments import dict_argument, required_argument_string
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import (
    action_response_from_result,
    audit_event,
    finish_json_receipt,
    propagate_dependency_blocked,
    require_action,
    require_approval,
    require_attempt,
    require_plan,
    resolve_existing_action_receipt,
    resolve_snapshot_fallback_resource_id,
)
from google_work_agent.application.write_verification_projection import (
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)
from google_work_agent.domain import (
    ActionCommand,
    ActionStatus,
    EffectType,
    ExecutionAttemptStatus,
    ResultCode,
    VerificationStatus,
    canonicalize_json_value,
    transition_action,
)
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceType,
    TraceEventRecord,
    UnitOfWork,
    VerificationRecord,
)

VERIFICATION_NORMALIZER_VERSION = "2026-08-06.p0"

DELETE_TOOL_TARGETS: dict[str, tuple[ResourceType, str, str]] = {
    "calendar_delete_event": (ResourceType.CALENDAR_EVENT, "event_id", "calendar_id"),
    "tasks_delete_task": (ResourceType.TASK, "task_id", "task_list_id"),
}


@dataclass(frozen=True, slots=True)
class VerifyActionCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    verification_id: str


@dataclass(frozen=True, slots=True)
class VerifyActionResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    approval_id: str | None = None
    attempt_id: str | None = None
    claim_token: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: WriteActionResponse) -> VerifyActionResult:
    return VerifyActionResult(
        applied=response.applied,
        result_code=response.result_code,
        action_id=response.action_id,
        action_status=response.action_status,
        action_version=response.action_version,
        next_allowed_commands=response.next_allowed_commands,
        approval_id=response.approval_id,
        attempt_id=response.attempt_id,
        claim_token=response.claim_token,
        safe_error_code=response.safe_error_code,
        conflict_detail=response.conflict_detail,
    )


class VerifyActionHandler:
    """Verify external effect without ever issuing a write or retry."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        connector_execution: ConnectorWritePort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._connector_execution = connector_execution

    def __call__(self, command: VerifyActionCommand) -> VerifyActionResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _to_result(
                    resolve_existing_action_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        action_id=command.action_id,
                        now_ms=self._now_ms(),
                    )
                )

            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)
            if approval.action_id != action.id:
                return self._store_state_conflict(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    attempt=attempt,
                    detail="verification attempt does not belong to the requested action",
                )
            if attempt.status is not ExecutionAttemptStatus.SUCCEEDED:
                return self._store_state_conflict(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    attempt=attempt,
                    detail="verification requires a succeeded execution attempt",
                )
            fallback_resource_id = resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=attempt.result_resource_ref_id,
            )

        delete_target_absent = False
        mcp_request_id: str | None = None
        if action.tool_name in DELETE_TOOL_TARGETS:
            try:
                actual_snapshot = self._connector_execution.fetch_verification_snapshot(
                    tool_name=action.tool_name,
                    arguments=loads(action.arguments_json),
                    fallback_resource_id=fallback_resource_id,
                )
                mcp_request_id = getattr(self._connector_execution, "last_request_id", None)
            except LookupError:
                delete_target_absent = True
                actual_snapshot = None
            except GoogleWorkspaceGatewayError as error:
                if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                    raise
                delete_target_absent = True
                actual_snapshot = None
                mcp_request_id = error.mcp_request_id
        else:
            actual_snapshot = self._connector_execution.fetch_verification_snapshot(
                tool_name=action.tool_name,
                arguments=loads(action.arguments_json),
                fallback_resource_id=fallback_resource_id,
            )
            mcp_request_id = getattr(self._connector_execution, "last_request_id", None)

        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _to_result(
                    resolve_existing_action_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        action_id=command.action_id,
                        now_ms=self._now_ms(),
                    )
                )

            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            approval = require_approval(unit_of_work, attempt.approval_id)
            if approval.action_id != action.id:
                return self._store_state_conflict(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    attempt=attempt,
                    detail="verification attempt does not belong to the requested action",
                )
            if attempt.status is not ExecutionAttemptStatus.SUCCEEDED:
                return self._store_state_conflict(
                    unit_of_work=unit_of_work,
                    command=command,
                    action=action,
                    attempt=attempt,
                    detail="verification requires a succeeded execution attempt",
                )
            plan = require_plan(unit_of_work, action.plan_id)
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="VerifyAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )

            expected = loads(action.expected_json)
            if action.tool_name in DELETE_TOOL_TARGETS:
                delete_resource_type, delete_id_field, _parent_field = DELETE_TOOL_TARGETS[
                    action.tool_name
                ]
                actual_projection: dict[str, object] = {
                    "resource_type": delete_resource_type.value,
                    "resource_id": required_argument_string(
                        dict_argument(loads(action.arguments_json)), delete_id_field
                    ),
                    "absent": delete_target_absent,
                }
                diff = (
                    []
                    if delete_target_absent
                    else [{"path": "$.absent", "expected": True, "actual": False}]
                )
                verification_status = (
                    VerificationStatus.VERIFIED
                    if delete_target_absent
                    else VerificationStatus.MISMATCH
                )
            else:
                if actual_snapshot is None:
                    raise RuntimeError("verification snapshot is required")
                actual_projection = normalize_actual_verification_projection(
                    tool_name=action.tool_name,
                    actual=normalize_snapshot(actual_snapshot),
                )
                diff = calculate_verification_subset_diff(expected, actual_projection)
                verification_status = (
                    VerificationStatus.VERIFIED if not diff else VerificationStatus.MISMATCH
                )

            preview = transition_action(
                ActionStatus(action.status),
                command=ActionCommand.STORE_VERIFICATION,
                current_version=action.version,
                expected_version=command.expected_action_version,
                effect_type=EffectType(action.effect_type),
                verification_status=verification_status,
            )
            if not preview.applied:
                response = action_response_from_result(action_id=action.id, result=preview)
                finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    preview.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return _to_result(response)

            verification_no = len(unit_of_work.verifications.list_by_attempt(attempt.id)) + 1
            verification = VerificationRecord(
                id=command.verification_id,
                execution_attempt_id=attempt.id,
                verification_no=verification_no,
                status=verification_status,
                normalizer_version=VERIFICATION_NORMALIZER_VERSION,
                expected_json=canonicalize_json_value(expected),
                actual_json=canonicalize_json_value(actual_projection),
                diff_json=canonicalize_json_value(diff),
                verified_at_ms=now_ms,
            )
            unit_of_work.verifications.insert(verification)
            transition = unit_of_work.actions.store_verification(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
                verification_status=verification_status.value,
            )
            if not transition.applied:
                raise RuntimeError("validated verification transition was not applied")

            if verification_status is VerificationStatus.MISMATCH:
                propagate_dependency_blocked(
                    unit_of_work=unit_of_work,
                    action_id=action.id,
                    run_id=plan.run_id,
                    updated_at_ms=now_ms,
                )
                unit_of_work.runs.set_recovery_required(plan.run_id)

            trace_payload: dict[str, object] = {
                "attempt_id": attempt.id,
                "verification_id": verification.id,
            }
            if mcp_request_id is not None:
                trace_payload["mcp_request_id"] = mcp_request_id
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_VERIFIED",
                    status=verification_status.value,
                    duration_ms=None,
                    payload_json=dumps(trace_payload, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            audit_metadata = dict(trace_payload)
            audit_metadata["verification_status"] = verification_status.value
            unit_of_work.audits.add(
                audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_VERIFIED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata=audit_metadata,
                    created_at_ms=now_ms,
                )
            )
            response = WriteActionResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                action_id=action.id,
                action_status=transition.current_status.value,
                action_version=transition.current_version,
                next_allowed_commands=tuple(item.value for item in transition.next_allowed_commands),
                attempt_id=attempt.id,
            )
            finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                transition.current_version,
                now_ms,
            )
            unit_of_work.commit()
            return _to_result(response)

    def _store_state_conflict(
        self,
        *,
        unit_of_work: UnitOfWork,
        command: VerifyActionCommand,
        action: object,
        attempt: object,
        detail: str,
    ) -> VerifyActionResult:
        now_ms = self._now_ms()
        unit_of_work.command_receipts.add_received(
            command_id=command.command_id,
            command_type="VerifyAction",
            request_hash=command.request_hash,
            aggregate_type="Action",
            aggregate_id=command.action_id,
            created_at_ms=now_ms,
        )
        response = WriteActionResponse(
            applied=False,
            result_code=ResultCode.STATE_CONFLICT.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
            attempt_id=attempt.id,
            conflict_detail=detail,
        )
        finish_json_receipt(
            unit_of_work,
            command.command_id,
            response,
            action.version,
            now_ms,
        )
        unit_of_work.commit()
        return _to_result(response)
