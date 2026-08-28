"""Persist a definitive NOT_SENT write failure."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_execution_attempt_record,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    finish_json_receipt,
    propagate_dependency_blocked,
    require_action,
    require_attempt,
    require_plan,
    resolve_existing_action_receipt,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.mark_failed import (
    transition_mark_failed,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.connector.contracts.google_workspace import DeliveryCertainty
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class MarkFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    delivery_certainty: DeliveryCertainty
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class MarkFailedResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: WriteActionResponse) -> MarkFailedResult:
    return MarkFailedResult(
        applied=response.applied,
        result_code=response.result_code,
        action_id=response.action_id,
        action_status=response.action_status,
        action_version=response.action_version,
        next_allowed_commands=response.next_allowed_commands,
        attempt_id=response.attempt_id,
        safe_error_code=response.safe_error_code,
        conflict_detail=response.conflict_detail,
    )


class MarkFailedHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkFailedCommand) -> MarkFailedResult:
        if command.delivery_certainty is not DeliveryCertainty.NOT_SENT:
            raise ValueError("FAILED requires delivery_certainty=NOT_SENT")
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
            now_ms = self._now_ms()
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="MarkFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            plan = require_plan(unit_of_work, action.plan_id)
            transition = transition_mark_failed(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
                delivery_certainty=command.delivery_certainty.value,
            )
            if not transition.applied:
                raise RuntimeError(transition.conflict_detail or "MarkFailed rejected")
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
                    next_status=transition.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated MarkFailed CAS failed")
            propagate_dependency_blocked(
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
                audit_event(
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
                action_status=transition.current_status.value,
                action_version=transition.current_version,
                next_allowed_commands=tuple(
                    item.value for item in transition.next_allowed_commands
                ),
                attempt_id=attempt.id,
                safe_error_code=command.error_code,
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
