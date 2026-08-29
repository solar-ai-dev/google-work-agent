"""Persist an existing external result recovered from UNKNOWN_RESULT."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import JSONDecodeError, dumps, loads

from google_work_agent.application.use_cases.action.persistence_cas import (
    update_action_record,
    update_execution_attempt_record,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event,
    finish_json_receipt,
    require_action,
    require_attempt,
    require_plan,
    resolve_existing_action_receipt,
    upsert_resource_ref,
    write_action_version_conflict_response,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.application.use_cases.resource_ref.resource_ref_projection import (
    resource_ref_from_snapshot,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.execution_attempt.transitions.recover_existing_result import (
    transition_recover_existing_result,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.connector.contracts.google_workspace import ResourceSnapshot
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class RecoverExistingResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    snapshot: ResourceSnapshot
    safe_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class RecoverExistingResultResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: WriteActionResponse) -> RecoverExistingResultResult:
    return RecoverExistingResultResult(
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


class RecoverExistingResultHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RecoverExistingResultCommand) -> RecoverExistingResultResult:
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
                command_type="RecoverExistingResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            plan = require_plan(unit_of_work, action.plan_id)
            if action.version != command.expected_action_version:
                return self._finish_version_conflict(
                    unit_of_work,
                    command,
                    action,
                    attempt.id,
                    now_ms,
                    "expected_action_version does not match current_version",
                )
            if attempt.version != command.expected_attempt_version:
                return self._finish_version_conflict(
                    unit_of_work,
                    command,
                    action,
                    attempt.id,
                    now_ms,
                    "expected_attempt_version does not match current_version",
                )
            resource_ref = resource_ref_from_snapshot(
                run_id=plan.run_id,
                connector_id=action.connector_id,
                snapshot=command.snapshot,
                captured_at_ms=now_ms,
            )
            persisted_resource_ref = upsert_resource_ref(
                unit_of_work=unit_of_work,
                resource_ref=resource_ref,
            )
            update_execution_attempt_record(
                unit_of_work,
                attempt.id,
                expected_version=command.expected_attempt_version,
                expected_status=attempt.status,
                status=ExecutionAttemptStatusV1.SUCCEEDED,
                error_code=command.safe_error_code,
                error_detail_json=None,
                result_resource_ref_id=persisted_resource_ref.id,
                response_metadata_json=_merge_response_metadata(
                    attempt.response_metadata_json,
                    operation=action.tool_name,
                    resource_id=command.snapshot.resource_id,
                ),
                finished_at_ms=now_ms,
            )
            transition = transition_recover_existing_result(
                ActionStatusV1(action.status),
                action_version=action.version,
                expected_action_version=command.expected_action_version,
                attempt_status=attempt.status,
                attempt_version=attempt.version,
                expected_attempt_version=command.expected_attempt_version,
            )
            if not transition.applied:
                raise RuntimeError(transition.conflict_detail or "RecoverExistingResult rejected")
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
                raise RuntimeError("validated RecoverExistingResult CAS failed")
            unit_of_work.traces.append(
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
            unit_of_work.audits.append(
                audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_RECOVERED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={
                        "attempt_id": attempt.id,
                        "resource_ref_id": persisted_resource_ref.id,
                    },
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

    def _finish_version_conflict(
        self,
        unit_of_work: UnitOfWork,
        command: RecoverExistingResultCommand,
        action: object,
        attempt_id: str,
        now_ms: int,
        detail: str,
    ) -> RecoverExistingResultResult:
        response = write_action_version_conflict_response(
            action=action,  # type: ignore[arg-type]
            attempt_id=attempt_id,
            conflict_detail=detail,
        )
        finish_json_receipt(unit_of_work, command.command_id, response, action.version, now_ms)  # type: ignore[attr-defined]
        unit_of_work.commit()
        return _to_result(response)


def _merge_response_metadata(
    existing_json: str | None, *, operation: str, resource_id: str
) -> str:
    if existing_json is None:
        metadata: dict[str, object] = {}
    else:
        try:
            parsed = loads(existing_json)
        except JSONDecodeError as error:
            raise RuntimeError("ExecutionAttempt response metadata is malformed") from error
        if not isinstance(parsed, dict):
            raise RuntimeError("ExecutionAttempt response metadata must be an object")
        metadata = dict(parsed)
    metadata.update({"operation": operation, "resource_id": resource_id})
    return dumps(metadata, sort_keys=True)
