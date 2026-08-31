"""Test-only historical cancellation workflow."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from json import dumps

from google_work_agent.application.use_cases.action.write_persistence import (
    audit_event as _audit_event,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    require_run as _require_run,
)
from google_work_agent.application.use_cases.action.write_persistence import (
    resolve_existing_run_receipt,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteRunResponse,
)
from google_work_agent.application.use_cases.plan.persistence_projection import current_plan_tuple
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run, RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.request_cancel import transition_request_cancel
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class _RunMutationResult:
    applied: bool
    result_code: ResultCode
    current_status: RunStatusV1
    current_version: int
    next_allowed_commands: tuple[object, ...] = ()
    conflict_detail: str | None = None


@dataclass(frozen=True, slots=True)
class RequestRunCancellationCommand:
    command_id: str
    request_hash: str
    run_id: str
    expected_run_version: int


def _apply_run_transition(
    unit_of_work: UnitOfWork,
    run: Run,
    expected_version: int,
    transition: Callable[[RunStatusV1], RunStatusV1],
    *,
    finished_at_ms: int | None = None,
) -> _RunMutationResult:
    if run.version != expected_version:
        return _RunMutationResult(
            False,
            ResultCode.VERSION_CONFLICT,
            run.status,
            run.version,
            conflict_detail="expected_version does not match current_version",
        )
    try:
        next_status = transition(run.status)
    except RunTransitionRejected as error:
        return _RunMutationResult(
            False, ResultCode.STATE_CONFLICT, run.status, run.version, conflict_detail=str(error)
        )
    values: dict[str, object] = {"status": next_status.value, "version": run.version + 1}
    if finished_at_ms is not None:
        values["finished_at_ms"] = finished_at_ms
    if not unit_of_work.runs.update_if_version_and_status(
        run.id, run.version, frozenset({run.status}), values
    ):
        raise RuntimeError("validated Run transition CAS failed")
    return _RunMutationResult(True, ResultCode.TRANSITION_APPLIED, next_status, run.version + 1)


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
            unit_of_work.command_receipts.reserve_or_replay(
                command_id=command.command_id,
                command_type="RequestRunCancellation",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            plans = current_plan_tuple(unit_of_work.plans, run.id)
            plan = max(plans, key=lambda item: (item.revision_no, item.created_at_ms), default=None)
            cancel_result = _apply_run_transition(
                unit_of_work, run, command.expected_run_version, transition_request_cancel
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
            unit_of_work.traces.append(
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
            unit_of_work.audits.append(
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
