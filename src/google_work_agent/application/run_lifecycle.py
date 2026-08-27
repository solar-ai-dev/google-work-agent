"""Resume use case for the persisted run lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import cast

from google_work_agent.application.run_command_receipts import (
    finish_json_receipt as _finish_json_receipt,
)
from google_work_agent.application.run_command_receipts import (
    resolve_existing_receipt as _resolve_existing_receipt,
)
from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunCommand,
)
from google_work_agent.application.use_cases.run.resume_run import (
    ResumeRunResult as ResumeRunResponse,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import Run as RunRecord
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import UnitOfWork


class ResumeRunService:
    """Validate one resume command and persist an idempotent receipt."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, command: ResumeRunCommand) -> ResumeRunResponse:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(
                    ResumeRunResponse,
                    _resolve_existing_receipt(
                        unit_of_work=unit_of_work,
                        receipt=existing,
                        request_hash=command.request_hash,
                        response_type=ResumeRunResponse,
                        run_id=command.run_id,
                        now_ms=self._now_ms(),
                    ),
                )
                return ResumeRunResponse(
                    **{
                        **asdict(response),
                        "should_enqueue": False,
                        "request_replayed": True,
                    }
                )

            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(
                command_id=command.command_id,
                command_type="ResumeRun",
                request_hash=command.request_hash,
                aggregate_type="Run",
                aggregate_id=command.run_id,
                created_at_ms=now_ms,
            )
            run = _require_run(unit_of_work, command.run_id)
            latest_plan = _latest_plan_id(unit_of_work, command.run_id)
            unknown_result_exists = False
            if latest_plan is not None:
                unknown_result_exists = any(
                    action.status == ActionStatusV1.UNKNOWN_RESULT.value
                    for action in unit_of_work.actions.list_by_plan(latest_plan)
                )

            allowed_statuses = {
                "CONFIRMATION": {RunStatusV1.WAITING_CONFIRMATION},
                "REAUTH_COMPLETED": {RunStatusV1.REAUTH_REQUIRED},
                "SAFE_CHECKPOINT_RESUME": {RunStatusV1.BLOCKED},
                "RECOVERY_RECHECK": {RunStatusV1.RECOVERY_REQUIRED},
            }
            if command.expected_run_version != run.version:
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.VERSION_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="expected_run_version does not match current version",
                )
            elif unknown_result_exists and command.resume_kind != "RECOVERY_RECHECK":
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.RECOVERY_REQUIRED.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="unknown write results must be resolved before resume",
                )
            elif run.status not in allowed_statuses.get(command.resume_kind, set()):
                response = ResumeRunResponse(
                    applied=False,
                    result_code=ResultCode.STATE_CONFLICT.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=False,
                    request_replayed=False,
                    conflict_detail="run status does not allow manual resume",
                )
            else:
                response = ResumeRunResponse(
                    applied=True,
                    result_code=ResultCode.TRANSITION_APPLIED.value,
                    run_id=run.id,
                    run_status=run.status.value,
                    run_version=run.version,
                    should_enqueue=True,
                    request_replayed=False,
                )
            _finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


def _latest_plan_id(unit_of_work: UnitOfWork, run_id: str) -> str | None:
    plans = unit_of_work.plans.list_by_run(run_id)
    if not plans:
        return None
    return plans[-1].id


def _require_run(unit_of_work: UnitOfWork, run_id: str) -> RunRecord:
    run = unit_of_work.runs.get(run_id)
    if run is None:
        raise LookupError(f"run not found: {run_id}")
    return run
