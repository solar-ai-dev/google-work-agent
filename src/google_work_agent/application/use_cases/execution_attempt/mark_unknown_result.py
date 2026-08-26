"""Persist an uncertain dispatched write as UNKNOWN_RESULT."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.write_execution_contracts import WriteActionResponse
from google_work_agent.application.write_persistence import (
    audit_event,
    finish_json_receipt,
    require_action,
    require_attempt,
    require_plan,
    resolve_existing_action_receipt,
)
from google_work_agent.domain import ActionStatus, ResultCode, calculate_canonical_json_hash
from google_work_agent.ports import DeliveryCertainty, TraceEventRecord, UnitOfWork


@dataclass(frozen=True, slots=True)
class MarkUnknownResultCommand:
    command_id: str
    request_hash: str
    action_id: str
    attempt_id: str
    expected_action_version: int
    expected_attempt_version: int
    delivery_certainty: DeliveryCertainty
    error_code: str
    error_detail: str
    mcp_request_id: str | None = None


@dataclass(frozen=True, slots=True)
class MarkUnknownResultResult:
    applied: bool
    result_code: str
    action_id: str
    action_status: str
    action_version: int
    next_allowed_commands: tuple[str, ...]
    attempt_id: str | None = None
    safe_error_code: str | None = None
    conflict_detail: str | None = None


def _to_result(response: WriteActionResponse) -> MarkUnknownResultResult:
    return MarkUnknownResultResult(
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


class MarkUnknownResultHandler:
    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: MarkUnknownResultCommand) -> MarkUnknownResultResult:
        if command.delivery_certainty is DeliveryCertainty.NOT_SENT:
            raise ValueError("UNKNOWN_RESULT requires a possibly dispatched write")
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
                command_type="MarkUnknownResult",
                request_hash=command.request_hash,
                aggregate_type="Action",
                aggregate_id=command.action_id,
                created_at_ms=now_ms,
            )
            action = require_action(unit_of_work, command.action_id)
            attempt = require_attempt(unit_of_work, command.attempt_id)
            plan = require_plan(unit_of_work, action.plan_id)
            unit_of_work.execution_attempts.mark_unknown_result(
                attempt.id,
                expected_version=command.expected_attempt_version,
                error_code=command.error_code,
                error_detail_json=dumps({"detail": command.error_detail}, sort_keys=True),
                finished_at_ms=now_ms,
            )
            transition = unit_of_work.actions.mark_unknown_result(
                action.id,
                expected_version=command.expected_action_version,
                updated_at_ms=now_ms,
            )
            if not transition.applied:
                raise RuntimeError(
                    "mark_unknown_result action transition failed after attempt update"
                )
            run_before_recovery = unit_of_work.runs.get_by_id(plan.run_id)
            if run_before_recovery is None:
                raise LookupError(f"run not found: {plan.run_id}")
            fingerprint = calculate_canonical_json_hash(
                {
                    "action_id": action.id,
                    "execution_attempt_id": attempt.id,
                    "delivery_certainty": command.delivery_certainty.value,
                }
            )
            recovery = RequireRecoveryHandler.apply_in_unit_of_work(
                unit_of_work,
                RequireRecoveryCommand(
                    run_id=plan.run_id,
                    expected_version=run_before_recovery.version,
                    command_id=f"{command.command_id}:require-recovery",
                    request_hash=calculate_canonical_json_hash(
                        {
                            "command_id": f"{command.command_id}:require-recovery",
                            "fingerprint": fingerprint,
                        }
                    ),
                    reason="UNKNOWN_RESULT",
                    scope="ACTION",
                    recovery_fingerprint=fingerprint,
                    action_id=action.id,
                    execution_attempt_id=attempt.id,
                ),
                now_ms=now_ms,
            )
            if not recovery.applied:
                raise RuntimeError("unknown-result recovery transition was not applied")
            trace_payload: dict[str, object] = {
                "attempt_id": attempt.id,
                "error_code": command.error_code,
                "run_status": recovery.current_status,
                "delivery_certainty": command.delivery_certainty.value,
            }
            audit_metadata: dict[str, object] = {
                "attempt_id": attempt.id,
                "error_code": command.error_code,
                "delivery_certainty": command.delivery_certainty.value,
            }
            if command.mcp_request_id is not None:
                trace_payload["mcp_request_id"] = command.mcp_request_id
                audit_metadata["mcp_request_id"] = command.mcp_request_id
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_ACTION_UNKNOWN_RESULT",
                    status=ActionStatus.UNKNOWN_RESULT.value,
                    duration_ms=None,
                    payload_json=dumps(trace_payload, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                audit_event(
                    run_id=plan.run_id,
                    action_id=action.id,
                    event_type="WRITE_UNKNOWN_RESULT",
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
