"""Recovery workflows for uncertain and mismatched write results."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads
from typing import cast

from google_work_agent.application.ports import ConnectorExecutionPort
from google_work_agent.application.write_action_arguments import (
    dict_argument as _dict_argument,
)
from google_work_agent.application.write_action_arguments import (
    required_argument_string as _required_argument_string,
)
from google_work_agent.application.write_cancellation import (
    has_durable_cancel_intent as _has_durable_cancel_intent,
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
    cancel_pending_actions as _cancel_pending_actions,
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
    require_latest_plan_for_run as _require_latest_plan_for_run,
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
    resolve_existing_run_receipt as _resolve_existing_run_receipt,
)
from google_work_agent.application.write_persistence import (
    resolve_snapshot_fallback_resource_id as _resolve_snapshot_fallback_resource_id,
)
from google_work_agent.application.write_persistence import (
    resource_ref_from_snapshot as _resource_ref_from_snapshot,
)
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
    RecoveryResolutionKind,
    RequireWriteReauthCommand,
    ResolveMismatchRecoveryCommand,
    ResolveUnknownWriteAsFailedCommand,
)
from google_work_agent.application.write_verification import (
    DELETE_TOOL_TARGETS as _DELETE_TOOL_TARGETS,
)
from google_work_agent.application.write_verification import (
    normalize_verification_projection,
)
from google_work_agent.domain import (
    ActionStatus,
    ExecutionAttemptStatus,
    PolicyViolationError,
    ResultCode,
    RunCommand,
    RunStatus,
    transition_run,
)
from google_work_agent.ports import (
    ActionRecord,
    ExecutionAttemptRecord,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    PlanRecord,
    PlanStatus,
    ResourceSnapshot,
    TraceEventRecord,
    UnitOfWork,
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
            unit_of_work.execution_attempts.mark_unknown_result(
                attempt.id,
                expected_version=command.expected_attempt_version,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.mark_unknown_result(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action mark_unknown_result transition failed after attempt update"
                )
            run = unit_of_work.runs.set_recovery_required(plan.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_UNKNOWN_RESULT",
                    status=ActionStatus.UNKNOWN_RESULT.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {
                            "attempt_id": attempt.id,
                            "error_code": command.error_code,
                            "run_status": run.status.value,
                        },
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESULT",
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
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            unit_of_work.execution_attempts.update_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                status=ExecutionAttemptStatus.SUCCEEDED,
                error_code=command.safe_error_code,
                error_detail_json=None,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.recover_existing_result(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError("recover_existing_result action transition failed")
            unit_of_work.runs.set_verifying(plan.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_RECOVERED",
                    status=ActionStatus.EXECUTED.value,
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
            unit_of_work.execution_attempts.update_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                status=ExecutionAttemptStatus.FAILED,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.resolve_unknown_as_failed(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError("resolve_unknown_as_failed action transition failed")
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
                    status=ActionStatus.FAILED.value,
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
        gateway: ConnectorExecutionPort,
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
        gateway: ConnectorExecutionPort,
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
        gateway: ConnectorExecutionPort,
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
        gateway: ConnectorExecutionPort,
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
            result = unit_of_work.actions.prepare_write_retry(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
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
                    status=ActionStatus.MODIFIED.value,
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


class ResolveMismatchRecoveryService:
    """Resolve an immutable verification mismatch without reusing write authority."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveMismatchRecoveryCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResolveMismatchRecovery",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            action = _require_action(unit_of_work, command.action_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            if plan.run_id != run.id or action.status != ActionStatus.MISMATCH.value:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="recovery requires a MISMATCH action owned by the run",
                )
                return _finish_recovery_response(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    response=response,
                    now_ms=now_ms,
                )

            if _has_durable_cancel_intent(unit_of_work, run.id):
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail=(
                        "ACCEPT_PARTIAL and CREATE_CORRECTIVE_PLAN require "
                        "cancel_intent_active=false; use CANCEL instead"
                    ),
                )
                return _finish_recovery_response(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    response=response,
                    now_ms=now_ms,
                )

            next_status = (
                RunStatus.COMPLETED
                if command.resolution_kind is RecoveryResolutionKind.ACCEPT_PARTIAL
                else RunStatus.PLANNING
            )
            preview = transition_run(
                run.status,
                command=RunCommand.RESOLVE_RECOVERY,
                current_version=run.version,
                expected_version=command.expected_run_version,
                recovery_next_status=next_status,
            )
            if not preview.applied:
                response = WriteRunResponse(
                    applied=False,
                    result_code=preview.result_code.value,
                    run_id=run.id,
                    run_status=preview.current_status.value,
                    run_version=preview.current_version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail=preview.conflict_detail,
                )
                return _finish_recovery_response(
                    unit_of_work=unit_of_work,
                    command_id=command.command_id,
                    response=response,
                    now_ms=now_ms,
                )

            if command.resolution_kind is RecoveryResolutionKind.ACCEPT_PARTIAL:
                _cancel_pending_actions(
                    unit_of_work=unit_of_work,
                    run_id=run.id,
                    plan_id=plan.id,
                    updated_at_ms=now_ms,
                )
                unit_of_work.plans.complete(plan.id)
                result_plan = plan.id
                result_plan_status = PlanStatus.COMPLETED.value
                result_kind = "PARTIAL"
            else:
                if not command.corrective_plan_id:
                    raise ValueError("corrective_plan_id is required for CREATE_CORRECTIVE_PLAN")
                _revoke_active_approvals_for_plan(
                    unit_of_work=unit_of_work,
                    plan_id=plan.id,
                )
                unit_of_work.plans.supersede(plan.id)
                next_revision = (
                    max(item.revision_no for item in unit_of_work.plans.list_by_run(run.id)) + 1
                )
                corrective_plan = PlanRecord(
                    id=command.corrective_plan_id,
                    run_id=run.id,
                    revision_no=next_revision,
                    status=PlanStatus.DRAFT,
                    summary_text=f"Corrective plan for mismatch action {action.id}",
                    created_at_ms=now_ms,
                )
                unit_of_work.plans.insert_draft(corrective_plan)
                result_plan = corrective_plan.id
                result_plan_status = corrective_plan.status.value
                result_kind = "CORRECTIVE_PLAN_REQUIRED"

            resolved = unit_of_work.runs.resolve_recovery(
                run.id,
                expected_version=command.expected_run_version,
                recovery_next_status=next_status,
                finished_at_ms=now_ms if next_status is RunStatus.COMPLETED else None,
            )
            if not resolved.applied:
                raise RuntimeError("validated recovery transition was not applied")

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=action.id,
                    event_type="RECOVERY_RESOLVED",
                    status=resolved.current_status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"resolution_kind": command.resolution_kind.value}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=action.id,
                    event_type="RECOVERY_RESOLVED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"resolution_kind": command.resolution_kind.value},
                    created_at_ms=now_ms,
                )
            )
            response = WriteRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=run.id,
                run_status=resolved.current_status.value,
                run_version=resolved.current_version,
                plan_id=result_plan,
                plan_status=result_plan_status,
                result_kind=result_kind,
            )
            return _finish_recovery_response(
                unit_of_work=unit_of_work,
                command_id=command.command_id,
                response=response,
                now_ms=now_ms,
            )


class RequireWriteReauthService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequireWriteReauthCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return _resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RequireWriteReauth",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            updated_run = unit_of_work.runs.set_reauth_required(command.run_id)
            plan = _require_latest_plan_for_run(unit_of_work, command.run_id)
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=command.run_id,
                    action_id=command.action_id,
                    event_type="RUN_REAUTH_REQUIRED",
                    status=updated_run.status.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"safe_error_code": command.safe_error_code},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=command.run_id,
                    action_id=command.action_id,
                    event_type="RUN_REAUTH_REQUIRED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"safe_error_code": command.safe_error_code},
                    created_at_ms=now_ms,
                )
            )
            response = WriteRunResponse(
                applied=True,
                result_code=ResultCode.TRANSITION_APPLIED.value,
                run_id=command.run_id,
                run_status=updated_run.status.value,
                run_version=updated_run.version,
                plan_id=plan.id,
                plan_status=plan.status.value,
                result_kind="REAUTH_REQUIRED",
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response


def _revoke_active_approvals_for_plan(*, unit_of_work: UnitOfWork, plan_id: str) -> None:
    for action in unit_of_work.actions.list_by_plan(plan_id):
        unit_of_work.approvals.revoke_active_by_action(action.id)


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
