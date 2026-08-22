"""Resume one persisted run from an allowed safe checkpoint."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import cast

from google_work_agent.application.run_command_receipts import finish_json_receipt, resolve_existing_receipt
from google_work_agent.application.run_contracts import ResumeRunCommand, ResumeRunResponse as ResumeRunResult
from google_work_agent.domain import ActionStatus, ResultCode, RunStatus
from google_work_agent.ports import UnitOfWork


class ResumeRunHandler:
    """Own resume eligibility, receipt truth, and coordinator handoff."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int], enqueue_resume: Callable[..., None]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._enqueue_resume = enqueue_resume

    @classmethod
    def from_legacy_service_supplier(cls, service_supplier: Callable[[], object], coordinator: object) -> "ResumeRunHandler":
        service = service_supplier()
        return cls(unit_of_work_factory=service._unit_of_work_factory, now_ms=service._now_ms, enqueue_resume=coordinator.enqueue_resume)  # type: ignore[attr-defined]

    def __call__(self, command: ResumeRunCommand, *, request_id: str, resume_payload: dict[str, object] | None = None) -> ResumeRunResult:
        result = self._persist(command)
        if result.applied and result.should_enqueue:
            self._enqueue_resume(run_id=command.run_id, request_id=request_id, command_id=command.command_id, resume_kind=command.resume_kind, resume_payload={} if resume_payload is None else resume_payload)
        return result

    def _persist(self, command: ResumeRunCommand) -> ResumeRunResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                response = cast(ResumeRunResult, resolve_existing_receipt(unit_of_work=unit_of_work, receipt=existing, request_hash=command.request_hash, response_type=ResumeRunResult, run_id=command.run_id, now_ms=self._now_ms()))
                return ResumeRunResult(**{**asdict(response), "should_enqueue": False, "request_replayed": True})
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="ResumeRun", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
            run = unit_of_work.runs.get_by_id(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            plans = unit_of_work.plans.list_by_run(command.run_id)
            latest_plan = None if not plans else plans[-1]
            unknown_result_exists = False if latest_plan is None else any(action.status == ActionStatus.UNKNOWN_RESULT.value for action in unit_of_work.actions.list_by_plan(latest_plan.id))
            allowed_statuses = {
                "CONFIRMATION": {RunStatus.WAITING_CONFIRMATION},
                "REAUTH_COMPLETED": {RunStatus.REAUTH_REQUIRED},
                "SAFE_CHECKPOINT_RESUME": {RunStatus.BLOCKED},
                "RECOVERY_RECHECK": {RunStatus.RECOVERY_REQUIRED},
            }
            if command.expected_run_version != run.version:
                response = ResumeRunResult(applied=False, result_code=ResultCode.VERSION_CONFLICT.value, run_id=run.id, run_status=run.status.value, run_version=run.version, should_enqueue=False, request_replayed=False, conflict_detail="expected_run_version does not match current version")
            elif unknown_result_exists and command.resume_kind != "RECOVERY_RECHECK":
                response = ResumeRunResult(applied=False, result_code=ResultCode.RECOVERY_REQUIRED.value, run_id=run.id, run_status=run.status.value, run_version=run.version, should_enqueue=False, request_replayed=False, conflict_detail="unknown write results must be resolved before resume")
            elif run.status not in allowed_statuses.get(command.resume_kind, set()):
                response = ResumeRunResult(applied=False, result_code=ResultCode.STATE_CONFLICT.value, run_id=run.id, run_status=run.status.value, run_version=run.version, should_enqueue=False, request_replayed=False, conflict_detail="run status does not allow manual resume")
            else:
                response = ResumeRunResult(applied=True, result_code=ResultCode.TRANSITION_APPLIED.value, run_id=run.id, run_status=run.status.value, run_version=run.version, should_enqueue=True, request_replayed=False)
            finish_json_receipt(unit_of_work, command.command_id, response, run.version, now_ms)
            unit_of_work.commit()
            return response


__all__ = ["ResumeRunCommand", "ResumeRunHandler", "ResumeRunResult"]
