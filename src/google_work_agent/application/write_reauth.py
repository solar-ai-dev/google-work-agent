"""CommandResult-aware reauthentication boundary for write execution."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.write_execution_contracts import WriteRunResponse
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
    finish_json_receipt as _finish_json_receipt,
    require_latest_plan_for_run as _require_latest_plan_for_run,
    require_run as _require_run,
    resolve_existing_run_receipt as _resolve_existing_run_receipt,
)
from google_work_agent.application.write_recovery_contracts import RequireWriteReauthCommand
from google_work_agent.domain import ResultCode
from google_work_agent.ports import TraceEventRecord, UnitOfWork


class RequireWriteReauthService:
    """Persist REAUTH_REQUIRED only when the Domain command is actually applied."""

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
                    now_ms=self._now_ms(),
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
            run = _require_run(unit_of_work, command.run_id)
            plan = _require_latest_plan_for_run(unit_of_work, command.run_id)
            result = unit_of_work.runs.require_reauth(
                command.run_id,
                expected_version=run.version,
                finished_at_ms=None,
            )
            response = WriteRunResponse(
                applied=bool(result.applied),
                result_code=result.result_code.value,
                run_id=command.run_id,
                run_status=result.current_status.value,
                run_version=result.current_version,
                plan_id=plan.id,
                plan_status=plan.status.value,
                result_kind="REAUTH_REQUIRED" if result.applied else None,
                conflict_detail=result.conflict_detail,
            )
            if result.applied:
                trace_payload: dict[str, object] = {"safe_error_code": command.safe_error_code}
                audit_metadata: dict[str, object] = {"safe_error_code": command.safe_error_code}
                if command.mcp_request_id is not None:
                    trace_payload["mcp_request_id"] = command.mcp_request_id
                    audit_metadata["mcp_request_id"] = command.mcp_request_id
                unit_of_work.traces.add(
                    TraceEventRecord(
                        run_id=command.run_id,
                        action_id=command.action_id,
                        event_type="RUN_REAUTH_REQUIRED",
                        status=result.current_status.value,
                        duration_ms=None,
                        payload_json=dumps(trace_payload, sort_keys=True),
                        created_at_ms=now_ms,
                    )
                )
                unit_of_work.audits.add(
                    _audit_event(
                        run_id=command.run_id,
                        action_id=command.action_id,
                        event_type="RUN_REAUTH_REQUIRED",
                        outcome=ResultCode.TRANSITION_APPLIED.value,
                        metadata=audit_metadata,
                        created_at_ms=now_ms,
                    )
                )
            _finish_json_receipt(
                unit_of_work,
                command.command_id,
                response,
                response.run_version,
                now_ms,
            )
            unit_of_work.commit()
            return response


__all__ = ["RequireWriteReauthService"]
