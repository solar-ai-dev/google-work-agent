"""Recovery workflows for uncertain and mismatched write results."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads
from typing import cast

from google_work_agent.application.resource_ref_projection import (
    resource_ref_from_snapshot as _resource_ref_from_snapshot,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.write_action_arguments import (
    dict_argument as _dict_argument,
)
from google_work_agent.application.write_action_arguments import (
    required_argument_string as _required_argument_string,
)
from google_work_agent.application.write_execution_contracts import (
    WriteActionResponse,
    WriteRunResponse,
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
    require_approval as _require_approval,
)
from google_work_agent.application.write_persistence import (
    require_attempt as _require_attempt,
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
from google_work_agent.application.write_persistence import (
    resolve_snapshot_fallback_resource_id as _resolve_snapshot_fallback_resource_id,
)
from google_work_agent.application.write_persistence import revoke_active_approvals
from google_work_agent.application.write_persistence import (
    upsert_resource_ref as _upsert_resource_ref,
)
from google_work_agent.application.write_persistence import (
    write_action_version_conflict_response as _write_action_version_conflict_response,
)
from google_work_agent.application.write_recovery_contracts import (
    MarkWriteActionUnknownResultCommand,
    PrepareWriteRetryCommand,
    RecoverExistingWriteResultCommand,
    RecoverUnknownCreateActionCommand,
    RecoverUnknownDeleteActionCommand,
    RecoverUnknownSendActionCommand,
    RecoverUnknownUpdateActionCommand,
    ResolveUnknownWriteAsFailedCommand,
)
from google_work_agent.application.write_verification import (
    DELETE_TOOL_TARGETS as _DELETE_TOOL_TARGETS,
)
from google_work_agent.application.write_verification import (
    normalize_verification_projection,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.action.transitions.prepare_write_retry import (
    transition_prepare_write_retry,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt as ExecutionAttemptRecord,
)
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.mark_unknown_result import (
    transition_mark_unknown_result,
)
from google_work_agent.domain.execution_attempt.transitions.recover_existing_result import (
    transition_recover_existing_result,
)
from google_work_agent.domain.execution_attempt.transitions.resolve_as_failed import (
    transition_resolve_as_failed,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.run.transitions.begin_verification import (
    transition_begin_verification,
)
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    UnitOfWork,
)
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
)


class MarkWriteActionUnknownResultService:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkWriteActionUnknownResultCommand) -> WriteActionResponse:
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
                command_type="MarkWriteActionUnknownResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            result = transition_mark_unknown_result(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
            )
            if not result.applied:
                raise RuntimeError(result.conflict_detail or "MarkUnknownResult rejected")
            unit_of_work.execution_attempts.update_if_version_and_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatusV1.UNKNOWN_RESULT,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            if (
                unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated MarkUnknownResult CAS failed")
            current_run = _require_run(unit_of_work, plan.run_id)
            recovery_fingerprint = calculate_canonical_json_hash(
                {
                    "action_id": action.id,
                    "execution_attempt_id": attempt.id,
                    "attempt_version": result.attempt_version,
                    "error_code": command.error_code,
                }
            )
            recovery = RequireRecoveryHandler.apply_in_unit_of_work(
                unit_of_work,
                RequireRecoveryCommand(
                    run_id=plan.run_id,
                    expected_version=current_run.version,
                    command_id=f"{command.command_id}:require-recovery",
                    request_hash=calculate_canonical_json_hash(
                        {
                            "command_id": f"{command.command_id}:require-recovery",
                            "fingerprint": recovery_fingerprint,
                        }
                    ),
                    reason="UNKNOWN_RESULT",
                    scope="ACTION",
                    recovery_fingerprint=recovery_fingerprint,
                    action_id=action.id,
                    execution_attempt_id=attempt.id,
                ),
                now_ms=now_ms,
            )
            if not recovery.applied:
                raise RuntimeError("unknown-result recovery transition was not applied")
            unknown_result_trace_payload: dict[str, object] = {
                "attempt_id": attempt.id,
                "error_code": command.error_code,
                "run_status": recovery.current_status,
            }
            unknown_result_audit_metadata: dict[str, object] = {
                "attempt_id": attempt.id,
                "error_code": command.error_code,
            }
            if command.mcp_request_id is not None:
                unknown_result_trace_payload["mcp_request_id"] = command.mcp_request_id
                unknown_result_audit_metadata["mcp_request_id"] = command.mcp_request_id
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_UNKNOWN_RESULT",
                    status=ActionStatusV1.UNKNOWN_RESULT.value,
                    duration_ms=None,
                    payload_json=dumps(unknown_result_trace_payload, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESULT",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata=unknown_result_audit_metadata,
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
                safe_error_code=command.error_code,
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


class RecoverExistingWriteResultService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RecoverExistingWriteResultCommand) -> WriteActionResponse:
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
                command_type="RecoverExistingWriteResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_action_version does not match current_version",
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
            if attempt.version != command.expected_attempt_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_attempt_version does not match current_version",
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
            resource_ref = _resource_ref_from_snapshot(
                run_id=plan.run_id,
                connector_id=action.connector_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            unit_of_work.execution_attempts.update_if_version_and_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatusV1.SUCCEEDED,
                error_code=command.safe_error_code,
                error_detail_json=None,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
            result = transition_recover_existing_result(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
            )
            if not result.applied:
                raise RuntimeError(result.conflict_detail or "RecoverExistingResult rejected")
            if (
                unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated RecoverExistingResult CAS failed")
            run = _require_run(unit_of_work, plan.run_id)
            if run.status in {
                RunStatusV1.WAITING_APPROVAL,
                RunStatusV1.CANCEL_REQUESTED,
            }:
                next_run_status = transition_begin_verification(run.status)
                if not unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {"status": next_run_status.value, "version": run.version + 1},
                ):
                    raise RuntimeError("validated BeginVerification CAS failed")
            elif run.status not in {
                RunStatusV1.VERIFYING,
                RunStatusV1.RECOVERY_REQUIRED,
            }:
                raise RuntimeError(
                    f"RecoverExistingResult cannot continue Run from {run.status.value}"
                )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_RECOVERED",
                    status=ActionStatusV1.EXECUTED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "resource_ref_id": persisted_resource_ref.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RECOVERED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"attempt_id": attempt.id, "resource_ref_id": resource_ref.id},
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


class ResolveUnknownWriteAsFailedService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveUnknownWriteAsFailedCommand) -> WriteActionResponse:
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
                command_type="ResolveUnknownWriteAsFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_action_version does not match current_version",
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
            if attempt.version != command.expected_attempt_version:
                response = _write_action_version_conflict_response(
                    action=action,
                    attempt_id=attempt.id,
                    conflict_detail="expected_attempt_version does not match current_version",
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
            unit_of_work.execution_attempts.update_if_version_and_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatusV1.FAILED,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            result = transition_resolve_as_failed(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
                result_not_executed_confirmed=True,
            )
            if not result.applied:
                raise RuntimeError(result.conflict_detail or "ResolveAsFailed rejected")
            if (
                unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ResolveAsFailed CAS failed")
            _propagate_dependency_blocked(
                unit_of_work=unit_of_work,
                action_id=action.id,
                run_id=plan.run_id,
                updated_at_ms=now_ms,
            )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESOLVED_FAILED",
                    status=ActionStatusV1.FAILED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "error_code": command.error_code},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RECOVERY_RESOLVED_FAILED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"attempt_id": attempt.id, "error_code": command.error_code},
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
                safe_error_code=command.error_code,
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


class RecoverUnknownCreateActionService:
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

    def __call__(self, command: RecoverUnknownCreateActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            approval = _require_approval(unit_of_work, attempt.approval_id)
        candidates = self._connector_execution.search_recovery_candidates(
            tool_name=action.tool_name,
            recovery_fingerprint=approval.recovery_fingerprint,
        )
        if len(candidates) != 1:
            return WriteActionResponse(
                applied=False,
                result_code=ResultCode.RECOVERY_REQUIRED.value,
                action_id=action.id,
                action_status=action.status,
                action_version=action.version,
                next_allowed_commands=(),
                attempt_id=attempt.id,
                conflict_detail="recovery search did not resolve to exactly one candidate",
            )
        return RecoverExistingWriteResultService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )(
            RecoverExistingWriteResultCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
                snapshot=candidates[0],
            )
        )


class RecoverUnknownSendActionService:
    """Recover an uncertain send by locating the existing sent message only."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
        gateway: ConnectorWritePort,
    ) -> None:
        self._delegate = RecoverUnknownCreateActionService(
            unit_of_work_factory=unit_of_work_factory,
            now_ms=now_ms,
            gateway=gateway,
        )

    def __call__(self, command: RecoverUnknownSendActionCommand) -> WriteActionResponse:
        return self._delegate(
            RecoverUnknownCreateActionCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
            )
        )


class RecoverUnknownDeleteActionService:
    """Reconcile an uncertain delete through target absence, never another delete call."""

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

    def __call__(self, command: RecoverUnknownDeleteActionCommand) -> WriteActionResponse:
        with self._unit_of_work_factory() as unit_of_work:
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            if action.tool_name not in _DELETE_TOOL_TARGETS:
                raise PolicyViolationError(
                    f"delete recovery requires a registered GET_ABSENT delete tool, "
                    f"got: {action.tool_name}"
                )
            arguments = _dict_argument(loads(action.arguments_json))
        try:
            self._connector_execution.fetch_verification_snapshot(
                tool_name=action.tool_name,
                arguments=arguments,
                fallback_resource_id=None,
            )
        except LookupError:
            return self._recover_absent_target(command=command, action=action, attempt=attempt)
        except GoogleWorkspaceGatewayError as error:
            if error.code is not GoogleWorkspaceErrorCode.NOT_FOUND:
                raise
            return self._recover_absent_target(command=command, action=action, attempt=attempt)
        return WriteActionResponse(
            applied=False,
            result_code=ResultCode.RECOVERY_REQUIRED.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
            attempt_id=attempt.id,
            conflict_detail="delete target is still present; blind re-delete is forbidden",
        )

    def _recover_absent_target(
        self,
        *,
        command: RecoverUnknownDeleteActionCommand,
        action: ActionRecord,
        attempt: ExecutionAttemptRecord,
    ) -> WriteActionResponse:
        arguments = _dict_argument(loads(action.arguments_json))
        resource_type, id_field, parent_field = _DELETE_TOOL_TARGETS[action.tool_name]
        parent_id = _required_argument_string(arguments, parent_field)
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="recovery-absence",
            resource_type=resource_type,
            resource_id=_required_argument_string(arguments, id_field),
            parent_id=parent_id,
            related_resource_ids=(parent_id,),
            version="deleted",
            recovery_fingerprint=None,
            payload={"deleted": True},
        )
        return RecoverExistingWriteResultService(
            unit_of_work_factory=self._unit_of_work_factory,
            now_ms=self._now_ms,
        )(
            RecoverExistingWriteResultCommand(
                command_id=command.command_id,
                request_hash=command.request_hash,
                action_id=command.action_id,
                attempt_id=command.attempt_id,
                expected_action_version=command.expected_action_version,
                expected_attempt_version=command.expected_attempt_version,
                snapshot=snapshot,
            )
        )


class RecoverUnknownUpdateActionService:
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

    def __call__(self, command: RecoverUnknownUpdateActionCommand) -> WriteActionResponse:
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
            approval = _require_approval(unit_of_work, attempt.approval_id)
            fallback_resource_id = _resolve_snapshot_fallback_resource_id(
                unit_of_work,
                action=action,
                resource_ref_id=action.target_resource_ref_id,
            )
        snapshot = self._connector_execution.fetch_verification_snapshot(
            tool_name=action.tool_name,
            arguments=loads(action.arguments_json),
            fallback_resource_id=fallback_resource_id,
        )
        normalized_actual = normalize_verification_projection(snapshot)
        expected_projection = cast(dict[str, object], loads(action.expected_json))
        if normalized_actual == expected_projection:
            return RecoverExistingWriteResultService(
                unit_of_work_factory=self._unit_of_work_factory,
                now_ms=self._now_ms,
            )(
                RecoverExistingWriteResultCommand(
                    command_id=command.command_id,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    attempt_id=command.attempt_id,
                    expected_action_version=command.expected_action_version,
                    expected_attempt_version=command.expected_attempt_version,
                    snapshot=snapshot,
                )
            )
        source_snapshot = cast(dict[str, object], loads(approval.source_snapshot_json))
        if normalized_actual == source_snapshot:
            return ResolveUnknownWriteAsFailedService(
                unit_of_work_factory=self._unit_of_work_factory,
                now_ms=self._now_ms,
            )(
                ResolveUnknownWriteAsFailedCommand(
                    command_id=command.command_id,
                    request_hash=command.request_hash,
                    action_id=command.action_id,
                    attempt_id=command.attempt_id,
                    expected_action_version=command.expected_action_version,
                    expected_attempt_version=command.expected_attempt_version,
                    error_code=GoogleWorkspaceErrorCode.NO_RECOVERY_CANDIDATE.value,
                    error_detail="target snapshot still matches source snapshot",
                )
            )
        return WriteActionResponse(
            applied=False,
            result_code=ResultCode.RECOVERY_REQUIRED.value,
            action_id=action.id,
            action_status=action.status,
            action_version=action.version,
            next_allowed_commands=(),
            attempt_id=attempt.id,
            conflict_detail="update recovery requires manual resolution",
        )


class PrepareWriteRetryService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: PrepareWriteRetryCommand) -> WriteActionResponse:
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
                command_type="PrepareWriteRetry",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            current_plan = max(
                unit_of_work.plans.list_by_run(plan.run_id),
                key=lambda candidate: getattr(candidate, "revision_no", 0),
                default=None,
            )
            result = transition_prepare_write_retry(
                ActionStatusV1(action.status),
                action.version,
                command.expected_action_version,
                effect_type=EffectType(action.effect_type),
                plan_status=plan.status,
                plan_is_current=current_plan is not None and current_plan.id == plan.id,
            )
            if (
                result.applied
                and unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatusV1(action.status),
                    next_status=result.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated PrepareWriteRetry CAS failed")
            if not result.applied:
                response = _action_response_from_result(action_id=action.id, result=result)
                _finish_json_receipt(
                    unit_of_work,
                    command.command_id,
                    response,
                    result.current_version,
                    now_ms,
                )
                unit_of_work.commit()
                return response
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    status=ActionStatusV1.MODIFIED.value,
                    duration_ms=None,
                    payload_json=dumps({"action_id": action.id}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RETRY_PREPARED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"action_id": action.id},
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


def _revoke_active_approvals_for_plan(*, unit_of_work: UnitOfWork, plan_id: str) -> None:
    for action in unit_of_work.actions.list_by_plan(plan_id):
        revoke_active_approvals(unit_of_work, action.id)


def _finish_recovery_response(
    *,
    unit_of_work: UnitOfWork,
    command_id: str,
    response: WriteRunResponse,
    now_ms: int,
) -> WriteRunResponse:
    _finish_json_receipt(
        unit_of_work,
        command_id,
        response,
        response.run_version,
        now_ms,
    )
    unit_of_work.commit()
    return response
