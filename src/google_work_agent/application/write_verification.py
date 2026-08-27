"""Pure normalization and comparison rules for write verification."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads
from typing import cast

from google_work_agent.application.write_action_arguments import (
    dict_argument as _dict_argument,
)
from google_work_agent.application.write_action_arguments import (
    required_argument_string as _required_argument_string,
)
from google_work_agent.application.write_execution_contracts import (
    VerifyWriteActionCommand,
    WriteActionResponse,
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
    propagate_dependency_blocked as _propagate_dependency_blocked,
)
from google_work_agent.application.write_persistence import (
    require_action as _require_action,
)
from google_work_agent.application.write_persistence import (
    require_attempt as _require_attempt,
)
from google_work_agent.application.write_persistence import (
    require_plan as _require_plan,
)
from google_work_agent.application.write_persistence import (
    resolve_existing_action_receipt as _resolve_existing_action_receipt,
)
from google_work_agent.application.write_persistence import (
    resolve_snapshot_fallback_resource_id as _resolve_snapshot_fallback_resource_id,
)
from google_work_agent.application.write_verification_projection import (
    calculate_verification_subset_diff,
    normalize_actual_verification_projection,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import canonicalize_json_value
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.domain.verification.model import Verification as VerificationRecord
from google_work_agent.domain.verification.model import VerificationStatus
from google_work_agent.domain.verification.transitions.store_verification import (
    transition_store_verification,
)
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
    UnitOfWork,
)
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
)

VERIFICATION_NORMALIZER_VERSION = "2026-08-06.p0"

DELETE_TOOL_TARGETS: dict[str, tuple[ResourceType, str, str]] = {
    "calendar_delete_event": (ResourceType.CALENDAR_EVENT, "event_id", "calendar_id"),
    "tasks_delete_task": (ResourceType.TASK, "task_id", "task_list_id"),
}


def normalize_verification_projection(snapshot: ResourceSnapshot) -> dict[str, object]:
    payload = dict(snapshot.payload)
    payload.pop("recovery_fingerprint", None)
    return {
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "version": snapshot.version,
        "payload": payload,
    }


def calculate_verification_diff(
    expected: object,
    actual: object,
    *,
    path: str = "$",
) -> list[dict[str, object]]:
    if type(expected) is not type(actual):
        return [{"path": path, "expected": expected, "actual": actual}]
    if isinstance(expected, dict) and isinstance(actual, dict):
        expected_map = cast(dict[str, object], expected)
        actual_map = cast(dict[str, object], actual)
        diffs: list[dict[str, object]] = []
        expected_keys = set(expected_map)
        actual_keys = set(actual_map)
        for key in sorted(expected_keys | actual_keys):
            if key not in expected_map or key not in actual_map:
                diffs.append(
                    {
                        "path": f"{path}.{key}",
                        "expected": expected_map.get(key, "<missing>"),
                        "actual": actual_map.get(key, "<missing>"),
                    }
                )
                continue
            diffs.extend(
                calculate_verification_diff(
                    expected_map[key],
                    actual_map[key],
                    path=f"{path}.{key}",
                )
            )
        return diffs
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            return [{"path": path, "expected": expected, "actual": actual}]
        list_diffs: list[dict[str, object]] = []
        for index, (expected_item, actual_item) in enumerate(zip(expected, actual, strict=False)):
            list_diffs.extend(
                calculate_verification_diff(expected_item, actual_item, path=f"{path}[{index}]")
            )
        return list_diffs
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


class VerifyWriteActionService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: ConnectorWritePort,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._connector_execution = gateway

    def __call__(self, command: VerifyWriteActionCommand) -> WriteActionResponse:
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

            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            if attempt.status is not ExecutionAttemptStatusV1.SUCCEEDED:
                now_ms = self._now_ms()
                unit_of_work.command_receipts.add_received(
                    command_id=command.command_id,
                    command_type="VerifyWriteAction",
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
                    conflict_detail="verification requires a succeeded execution attempt",
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
            fallback_resource_id = _resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=attempt.result_resource_ref_id,
            )

        delete_target_absent = False
        # mcp_request_id correlates this verification's trace/audit event
        # back to the specific MCP read that produced it. It stays None for
        # the LookupError branch below, where no MCP call was ever made
        # (the resource reference itself could not be resolved locally).
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
                return _resolve_existing_action_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    now_ms=self._now_ms(),
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="VerifyWriteAction",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if attempt.status is not ExecutionAttemptStatusV1.SUCCEEDED:
                response = WriteActionResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    action_id=action.id,
                    action_status=action.status,
                    action_version=action.version,
                    next_allowed_commands=(),
                    attempt_id=attempt.id,
                    conflict_detail="verification requires a succeeded execution attempt",
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

            expected = loads(action.expected_json)
            if action.tool_name in DELETE_TOOL_TARGETS:
                delete_resource_type, delete_id_field, _delete_parent_field = DELETE_TOOL_TARGETS[
                    action.tool_name
                ]
                actual_projection: dict[str, object] = {
                    "resource_type": delete_resource_type.value,
                    "resource_id": _required_argument_string(
                        _dict_argument(loads(action.arguments_json)), delete_id_field
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
                    actual=normalize_verification_projection(actual_snapshot),
                )
                diff = calculate_verification_subset_diff(expected, actual_projection)
                verification_status = (
                    VerificationStatus.VERIFIED if len(diff) == 0 else VerificationStatus.MISMATCH
                )
            preview = transition_store_verification(
                ActionStatusV1(action.status),
                current_version=action.version,
                expected_version=command.expected_action_version,
                verification_status=verification_status,
            )
            if not preview.applied:
                response = _action_response_from_result(action_id=action.id, result=preview)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    preview.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response

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
            if (
                unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=preview.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated StoreVerification CAS failed")
            result = preview
            if verification_status is VerificationStatus.MISMATCH:
                _propagate_dependency_blocked(
                    unit_of_work=unit_of_work,
                    action_id=action.id,
                    run_id=plan.run_id,
                    updated_at_ms=now_ms,
                )
                # A persisted mismatch is an immutable external fact; only an explicit
                # recovery decision may choose the next run transition.
                current_run = unit_of_work.runs.get(plan.run_id)
                if current_run is None:
                    raise LookupError(f"run not found: {plan.run_id}")
                next_run_status = transition_require_recovery(current_run.status)
                if not unit_of_work.runs.update_if_version_and_status(
                    current_run.id,
                    current_run.version,
                    frozenset({current_run.status}),
                    {"status": next_run_status.value, "version": current_run.version + 1},
                ):
                    raise RuntimeError("validated RequireRecovery CAS failed")

            verification_trace_payload: dict[str, object] = {
                "attempt_id": attempt.id,
                "verification_id": verification.id,
            }
            if mcp_request_id is not None:
                verification_trace_payload["mcp_request_id"] = mcp_request_id
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_VERIFIED",
                    status=verification_status.value,
                    duration_ms=None,
                    payload_json=dumps(verification_trace_payload, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            verification_audit_metadata: dict[str, object] = {
                "attempt_id": attempt.id,
                "verification_id": verification.id,
                "verification_status": verification_status.value,
            }
            if mcp_request_id is not None:
                verification_audit_metadata["mcp_request_id"] = mcp_request_id
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_VERIFIED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata=verification_audit_metadata,
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
                attempt_id=attempt.id,
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
