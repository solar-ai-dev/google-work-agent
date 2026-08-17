"""Cancellation workflow for write runs."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.write_cancellation_contracts import (
    FinalizeRunCancellationCommand,
    RequestRunCancellationCommand,
)
from google_work_agent.application.write_execution_contracts import WriteRunResponse
from google_work_agent.application.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.write_persistence import (
    cancel_pending_actions,
    resolve_existing_run_receipt,
)
from google_work_agent.application.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.write_persistence import (
    require_latest_plan_for_run as _require_latest_plan_for_run,
)
from google_work_agent.application.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.domain import ActionStatus, ResultCode, RunStatus
from google_work_agent.ports import (
    PlanStatus,
    TraceEventRecord,
    UnitOfWork,
)


class RequestRunCancellationService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: RequestRunCancellationCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="RequestRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plans = unit_of_work.plans.list_by_run(run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            actions = () if plan is None else unit_of_work.actions.list_by_plan(plan.id)
            cancel_result = unit_of_work.runs.request_cancel(
                run.id,
                expected_version=command.expected_run_version,
            )
            if not cancel_result.applied:
                response = WriteRunResponse(
                    applied=False,
                    result_code=cancel_result.result_code.value,
                    run_id=run.id,
                    run_status=cancel_result.current_status.value,
                    run_version=cancel_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    conflict_detail=cancel_result.conflict_detail,
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            has_started_write = any(
                action.status
                in {
                    ActionStatus.EXECUTING.value,
                    ActionStatus.UNKNOWN_RESULT.value,
                    ActionStatus.EXECUTED.value,
                    ActionStatus.VERIFIED.value,
                }
                for action in actions
            )
            if not has_started_write:
                if plan is not None:
                    cancel_pending_actions(
                        unit_of_work=unit_of_work,
                        run_id=run.id,
                        plan_id=plan.id,
                        updated_at_ms=now_ms,
                    )
                if plan is not None:
                    unit_of_work.plans.cancel(plan.id)
                final_result = unit_of_work.runs.finalize_cancel(
                    run.id,
                    expected_version=cancel_result.current_version,
                    finished_at_ms=now_ms,
                )
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=final_result.current_status.value,
                    run_version=final_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else PlanStatus.CANCELLED.value,
                    result_kind="CANCELLED",
                )
            else:
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=cancel_result.current_status.value,
                    run_version=cancel_result.current_version,
                    plan_id=None if plan is None else plan.id,
                    plan_status=None if plan is None else plan.status.value,
                    result_kind="CANCEL_REQUESTED",
                )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_REQUESTED",
                    status=response.run_status,
                    duration_ms=None,
                    payload_json=dumps(
                        {"plan_id": None if plan is None else plan.id}, sort_keys=True
                    ),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_REQUESTED",
                    outcome=ResultCode.TRANSITION_APPLIED.value,
                    metadata={"plan_id": None if plan is None else plan.id},
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


class FinalizeRunCancellationService:
    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int]
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: FinalizeRunCancellationCommand) -> WriteRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_run_receipt(
                    unit_of_work=unit_of_work,
                    receipt=existing,
                    request_hash=command.request_hash,
                    run_id=command.run_id,
                    now_ms=self._now_ms(),
                )
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="FinalizeRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plan = _require_latest_plan_for_run(unit_of_work, run.id)
            actions = unit_of_work.actions.list_by_plan(plan.id)
            if command.expected_run_version != run.version:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="expected_run_version does not match current version",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            finalize_expected_version = command.expected_run_version
            if run.status is RunStatus.VERIFYING:
                if not has_durable_cancel_intent(unit_of_work, run.id):
                    response = WriteRunResponse(
                        applied=False,
                        result_code=ResultCode.STATE_CONFLICT.value,
                        run_id=run.id,
                        run_status=run.status.value,
                        run_version=run.version,
                        plan_id=plan.id,
                        plan_status=plan.status.value,
                        conflict_detail=(
                            "verification can continue cancellation only after a successful "
                            "cancel request"
                        ),
                    )
                    _finish_json_receipt(
                        unit_of_work, command.command_id, response, run.version, now_ms
                    )
                    unit_of_work.commit()
                    return response
                continued_cancel = unit_of_work.runs.request_cancel(
                    run.id,
                    expected_version=run.version,
                )
                if not continued_cancel.applied:
                    response = WriteRunResponse(
                        applied=False,
                        result_code=continued_cancel.result_code.value,
                        run_id=run.id,
                        run_status=continued_cancel.current_status.value,
                        run_version=continued_cancel.current_version,
                        plan_id=plan.id,
                        plan_status=plan.status.value,
                        conflict_detail=continued_cancel.conflict_detail,
                    )
                    _finish_json_receipt(
                        unit_of_work,
                        command.command_id,
                        response,
                        continued_cancel.current_version,
                        now_ms,
                    )
                    unit_of_work.commit()
                    return response
                finalize_expected_version = continued_cancel.current_version
                run = _require_run(unit_of_work, command.run_id)
            elif run.status is not RunStatus.CANCEL_REQUESTED:
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="cancellation finalization requires cancel-requested state",
                )
                _finish_json_receipt(
                    unit_of_work, command.command_id, response, run.version, now_ms
                )
                unit_of_work.commit()
                return response
            if any(action.status == ActionStatus.UNKNOWN_RESULT.value for action in actions):
                recovery_run = unit_of_work.runs.set_recovery_required(run.id)
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.RECOVERY_REQUIRED.value,
                    run_id=run.id,
                    run_status=recovery_run.status.value,
                    run_version=recovery_run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    result_kind="RECOVERY_REQUIRED",
                    conflict_detail="unknown write results must be resolved before cancellation",
                )
            elif any(action.status == ActionStatus.EXECUTING.value for action in actions):
                response = WriteRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                    conflict_detail="cannot finalize cancellation while write is executing",
                )
            elif any(action.status == ActionStatus.EXECUTED.value for action in actions):
                updated_run = unit_of_work.runs.set_verifying(run.id)
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=updated_run.status.value,
                    run_version=updated_run.version,
                    plan_id=plan.id,
                    plan_status=plan.status.value,
                )
            else:
                cancel_pending_actions(
                    unit_of_work=unit_of_work,
                    run_id=run.id,
                    plan_id=plan.id,
                    updated_at_ms=now_ms,
                )
                final_result = unit_of_work.runs.finalize_cancel(
                    run.id,
                    expected_version=finalize_expected_version,
                    finished_at_ms=now_ms,
                )
                if not final_result.applied:
                    raise RuntimeError("validated cancellation finalization was not applied")
                unit_of_work.plans.cancel(plan.id)
                response = WriteRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=final_result.current_status.value,
                    run_version=final_result.current_version,
                    plan_id=plan.id,
                    plan_status=PlanStatus.CANCELLED.value,
                    result_kind=(
                        "PARTIAL"
                        if any(action.status == ActionStatus.VERIFIED.value for action in actions)
                        else "CANCELLED"
                    ),
                )
            unit_of_work.traces.add(
                TraceEventRecord(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_FINALIZED",
                    status=response.run_status,
                    duration_ms=None,
                    payload_json=dumps({"result_kind": response.result_kind}, sort_keys=True),
                    created_at_ms=now_ms,
                )
            )
            unit_of_work.audits.add(
                _audit_event(
                    run_id=run.id,
                    action_id=None,
                    event_type="RUN_CANCELLATION_FINALIZED",
                    outcome=response.result_code,
                    metadata={"result_kind": response.result_kind},
                    created_at_ms=now_ms,
                )
            )
            _finish_json_receipt(
                unit_of_work, command.command_id, response, response.run_version, now_ms
            )
            unit_of_work.commit()
            return response


def has_durable_cancel_intent(unit_of_work: UnitOfWork, run_id: str) -> bool:
    cursor: int | None = None
    while True:
        events = unit_of_work.audits.list_by_aggregate(
            run_id=run_id,
            cursor_after=cursor,
            limit=100,
        )
        if any(
            event.event_type == "RUN_CANCELLATION_REQUESTED"
            and event.outcome == ResultCode.TRANSITION_APPLIED.value
            for event in events
        ):
            return True
        if len(events) < 100:
            return False
        cursor = events[-1].id
