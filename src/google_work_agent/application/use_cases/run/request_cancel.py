"""Request durable cancellation for one run."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.write_cancellation_contracts import RequestRunCancellationCommand as RequestCancelCommand
from google_work_agent.application.write_execution_contracts import WriteRunResponse as RequestCancelResult
from google_work_agent.application.write_persistence import audit_event, cancel_pending_actions, finish_json_receipt, require_run, resolve_existing_run_receipt
from google_work_agent.domain import ActionStatus, ResultCode
from google_work_agent.ports import PlanStatus, TraceEventRecord, UnitOfWork


class RequestCancelHandler:
    """Own durable cancel truth and workflow cancellation handoff."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int], request_cancel: Callable[..., None]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._request_cancel = request_cancel

    @classmethod
    def from_legacy_service_supplier(cls, service_supplier: Callable[[], object], coordinator: object) -> "RequestCancelHandler":
        service = service_supplier()
        return cls(unit_of_work_factory=service._unit_of_work_factory, now_ms=service._now_ms, request_cancel=coordinator.request_cancel)  # type: ignore[attr-defined]

    def __call__(self, command: RequestCancelCommand, *, request_id: str) -> RequestCancelResult:
        result = self._persist(command)
        if result.applied and result.run_status == "CANCEL_REQUESTED":
            self._request_cancel(run_id=command.run_id, request_id=request_id, reason_code="user_requested")
        return result

    def _persist(self, command: RequestCancelCommand) -> RequestCancelResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_run_receipt(unit_of_work=unit_of_work, receipt=existing, request_hash=command.request_hash, run_id=command.run_id, now_ms=self._now_ms())
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="RequestRunCancellation", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
            run = require_run(unit_of_work, command.run_id)
            plans = unit_of_work.plans.list_by_run(run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            actions = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            cancel_result = unit_of_work.runs.request_cancel(run.id, expected_version=command.expected_run_version)
            if not cancel_result.applied:
                response = RequestCancelResult(applied=False, result_code=cancel_result.result_code.value, run_id=run.id, run_status=cancel_result.current_status.value, run_version=cancel_result.current_version, plan_id=None if plan is None else plan.id, plan_status=None if plan is None else plan.status.value, conflict_detail=cancel_result.conflict_detail)
                finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
                unit_of_work.commit()
                return response
            has_started_write = any(action.status in {ActionStatus.EXECUTING.value, ActionStatus.UNKNOWN_RESULT.value, ActionStatus.EXECUTED.value, ActionStatus.VERIFIED.value} for action in actions)
            if not has_started_write:
                if plan is not None:
                    cancel_pending_actions(unit_of_work=unit_of_work, run_id=run.id, plan_id=plan.id, updated_at_ms=now_ms)
                    unit_of_work.plans.cancel(plan.id)
                final_result = unit_of_work.runs.finalize_cancel(run.id, expected_version=cancel_result.current_version, finished_at_ms=now_ms)
                response = RequestCancelResult(applied=True, result_code=ResultCode.TRANSITION_APPLIED.value, run_id=run.id, run_status=final_result.current_status.value, run_version=final_result.current_version, plan_id=None if plan is None else plan.id, plan_status=None if plan is None else PlanStatus.CANCELLED.value, result_kind="CANCELLED")
            else:
                response = RequestCancelResult(applied=True, result_code=ResultCode.TRANSITION_APPLIED.value, run_id=run.id, run_status=cancel_result.current_status.value, run_version=cancel_result.current_version, plan_id=None if plan is None else plan.id, plan_status=None if plan is None else plan.status.value, result_kind="CANCEL_REQUESTED")
            unit_of_work.traces.add(TraceEventRecord(run_id=run.id, action_id=None, event_type="RUN_CANCELLATION_REQUESTED", status=response.run_status, duration_ms=None, payload_json=dumps({"plan_id": None if plan is None else plan.id}, sort_keys=True), created_at_ms=now_ms))
            unit_of_work.audits.add(audit_event(run_id=run.id, action_id=None, event_type="RUN_CANCELLATION_REQUESTED", outcome=ResultCode.TRANSITION_APPLIED.value, metadata={"plan_id": None if plan is None else plan.id}, created_at_ms=now_ms))
            finish_json_receipt(unit_of_work, command.command_id, response, response.run_version, now_ms)
            unit_of_work.commit()
            return response


__all__ = ["RequestCancelCommand", "RequestCancelHandler", "RequestCancelResult"]
