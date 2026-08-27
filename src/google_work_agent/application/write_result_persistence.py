"""Persistence of definitive write execution results."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.persistence_cas import (
    update_action_record,
    update_execution_attempt_record,
)
from google_work_agent.application.resource_ref_projection import (
    resource_ref_from_snapshot as _resource_ref_from_snapshot,
)
from google_work_agent.application.use_cases.execution_attempt.abort_claimed_execution import (
    AbortClaimedExecutionCommandV1,
    AbortClaimedExecutionHandler,
)
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
    upsert_resource_ref as _upsert_resource_ref,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.mark_failed import (
    transition_mark_failed,
)
from google_work_agent.domain.execution_attempt.transitions.store_success import (
    transition_store_success,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork


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
            unit_of_work.command_receipts.reserve_or_replay(
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
                connector_id=action.connector_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = _upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            preview = transition_store_success(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
            )
            if not preview.applied:
                response = WriteActionResponse(
                    applied=False,
                    result_code=preview.result_code.value,
                    action_id=action.id,
                    action_status=preview.current_status.value,
                    action_version=preview.current_version,
                    next_allowed_commands=(),
                    attempt_id=attempt.id,
                    conflict_detail=preview.conflict_detail,
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, action.version, now_ms
                )
                unit_of_work.commit()
                return response
            update_execution_attempt_record(
                unit_of_work,
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatusV1.SUCCEEDED,
                error_code=None,
                error_detail_json=None,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=dumps(
                    {"operation": action.tool_name, "resource_id": command.snapshot.resource_id},
                    sort_keys=True,
                ),
                finished_at_ms=now_ms,
            )
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
                raise RuntimeError("validated StoreSuccess Action CAS failed")
            result = preview

            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_EXECUTED",
                    status=ActionStatusV1.EXECUTED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "resource_ref_id": persisted_resource_ref.id},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
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
            unit_of_work.command_receipts.reserve_or_replay(
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
            if attempt.status is ExecutionAttemptStatusV1.CLAIMED:
                decision = AbortClaimedExecutionHandler.apply_in_unit_of_work(
                    unit_of_work,
                    AbortClaimedExecutionCommandV1(
                        command_id=f"abort-claimed-execution:{attempt.id}:{command.command_id}",
                        request_hash=calculate_canonical_json_hash(
                            {
                                "action_id": action.id,
                                "attempt_id": attempt.id,
                                "expected_action_version": command.expected_action_version,
                                "expected_attempt_version": command.expected_attempt_version,
                                "error_code": command.error_code,
                                "error_detail": command.error_detail,
                            }
                        ),
                        action_id=action.id,
                        attempt_id=attempt.id,
                        expected_action_version=command.expected_action_version,
                        expected_attempt_version=command.expected_attempt_version,
                        error_code=command.error_code,
                        error_detail=command.error_detail,
                    ),
                    now_ms=now_ms,
                )
                if not decision.applied:
                    raise RuntimeError(decision.conflict_detail or "AbortClaimedExecution rejected")
                result_status = decision.action_status
                result_version = decision.action_version
            else:
                preview = transition_mark_failed(
                    ActionStatusV1(action.status),
                    action_version=action.version,
                    expected_action_version=command.expected_action_version,
                    attempt_status=attempt.status,
                    attempt_version=attempt.version,
                    expected_attempt_version=command.expected_attempt_version,
                    delivery_certainty="NOT_SENT",
                )
                if not preview.applied:
                    raise RuntimeError(preview.conflict_detail or "MarkFailed rejected")
                update_execution_attempt_record(
                    unit_of_work,
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
                    raise RuntimeError("validated MarkFailed Action CAS failed")
                result_status = preview.current_status
                result_version = preview.current_version
            _propagate_dependency_blocked(
                unit_of_work=unit_of_work,
                action_id=action.id,
                run_id=plan.run_id,
                updated_at_ms=now_ms,
            )

            unit_of_work.traces.append(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_FAILED",
                    status=ActionStatusV1.FAILED.value,
                    duration_ms=None,
                    payload_json=dumps(
                        {"attempt_id": attempt.id, "error_code": command.error_code},
                        sort_keys=True,
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.append(
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
                action_status=result_status.value,
                action_version=result_version,
                next_allowed_commands=(),
                attempt_id=attempt.id,
                safe_error_code=command.error_code,
            )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                result_version,
                now_ms,
            )
            unit_of_work.commit()
            return response
