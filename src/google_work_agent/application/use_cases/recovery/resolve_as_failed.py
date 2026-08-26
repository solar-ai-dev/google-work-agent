"""Resolve UNKNOWN_RESULT as FAILED only after recovery proves no write occurred."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import (
    audit_event,
    finish_json_receipt,
    propagate_dependency_blocked,
    require_action,
    require_attempt,
    require_plan,
    resolve_existing_action_receipt,
    write_action_version_conflict_response,
)
from google_work_agent.domain.action.model import Action as ActionRecord
from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatus
from google_work_agent.domain.execution_attempt.transitions.resolve_as_failed import (
    transition_resolve_as_failed,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports import UnitOfWork


@dataclass(frozen=True, slots=True)
class ResolveAsFailedCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    error_code: str
    error_detail: str


@dataclass(frozen=True, slots=True)
class ResolveAsFailedResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: WriteActionResponse) -> ResolveAsFailedResult:
    return ResolveAsFailedResult(
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


class ResolveAsFailedHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResolveAsFailedCommand) -> ResolveAsFailedResult:
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
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResolveAsFailed",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            plan = require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                return self._finish_conflict(
                    unit_of_work,
                    command,
                    action,
                    attempt.id,
                    now_ms,
                    "expected_action_version does not match current_version",
                )
            if attempt.version != command.expected_attempt_version:
                return self._finish_conflict(
                    unit_of_work,
                    command,
                    action,
                    attempt.id,
                    now_ms,
                    "expected_attempt_version does not match current_version",
                )
            unit_of_work.execution_attempts.update_if_version_and_status(
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatus.FAILED,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                result_resource_ref_id=None,
                response_metadata_json=None,
                finished_at_ms=now_ms,
            )
            transition = transition_resolve_as_failed(
                ActionStatus(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
                result_not_executed_confirmed=True,
            )
            if not transition.applied:
                raise RuntimeError(transition.conflict_detail or "ResolveAsFailed rejected")
            if (
                unit_of_work.actions.update_if_version_and_status(
                    action.id,
                    expected_version=action.version,
                    expected_status=ActionStatus(action.status),
                    next_status=transition.current_status,
                    updated_at_ms=now_ms,
                )
                is None
            ):
                raise RuntimeError("validated ResolveAsFailed CAS failed")
            propagate_dependency_blocked(
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
                audit_event(
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

    def _finish_conflict(
        self,
        unit_of_work: UnitOfWork,
        command: ResolveAsFailedCommand,
        action: ActionRecord,
        attempt_id: str,
        now_ms: int,
        detail: str,
    ) -> ResolveAsFailedResult:
        response = write_action_version_conflict_response(
            action=action,
            attempt_id=attempt_id,
            conflict_detail=detail,
        )
        finish_json_receipt(unit_of_work, command.command_id, response, action.version, now_ms)
        unit_of_work.commit()
        return _to_result(response)
