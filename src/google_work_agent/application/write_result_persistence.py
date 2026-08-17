"""Persistence of definitive write execution results."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.write_execution_contracts import (
    MarkWriteActionFailedCommand,
    StoreWriteActionSuccessCommand,
    WriteActionResponse,
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
    resource_ref_from_snapshot as _resource_ref_from_snapshot,
)
from google_work_agent.application.write_persistence import (
    upsert_resource_ref as _upsert_resource_ref,
)
from google_work_agent.domain import ActionStatus, ResultCode
from google_work_agent.ports import TraceEventRecord, UnitOfWork


class StoreWriteActionSuccessService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: StoreWriteActionSuccessCommand) -> WriteActionResponse:
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
                command_type="StoreWriteActionSuccess",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)

            resource_ref = _resource_ref_from_snapshot(
                run_id=plan.run_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            unit_of_work.execution_attempts.mark_succeeded(
                attempt.id,
                expected_version=command.expected_attempt_version,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.store_success(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action store_success transition failed after attempt success"
                )

            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_EXECUTED",
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
                    event_type="WRITE_EXECUTED",
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


class MarkWriteActionFailedService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkWriteActionFailedCommand) -> WriteActionResponse:
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
                command_type="MarkWriteActionFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = _require_action(unit_of_work, command.action_id)
            attempt = _require_attempt(unit_of_work, command.attempt_id)
            plan = _require_plan(unit_of_work, action.plan_id)
            unit_of_work.execution_attempts.mark_failed(
                attempt.id,
                expected_version=command.expected_attempt_version,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                finished_at_ms=now_ms,
            )
            result = unit_of_work.actions.mark_failed(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not result.applied:
                raise RuntimeError(
                    "write action mark_failed transition failed after attempt failure"
                )
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
                    event_type="WRITE_ACTION_FAILED",
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
                    event_type="WRITE_FAILED",
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
