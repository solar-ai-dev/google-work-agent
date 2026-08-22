"""Resolve an API-exposed immutable verification mismatch."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from json import dumps, loads

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.write_persistence import audit_event, cancel_pending_actions
from google_work_agent.domain import ActionStatus, ResultCode, RunCommand, RunStatus, transition_run
from google_work_agent.ports import CommandReceiptStatus, PlanRecord, PlanStatus, TraceEventRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class MismatchRecoveryResolution(StrEnum):
    ACCEPT_PARTIAL = "ACCEPT_PARTIAL"
    CREATE_CORRECTIVE_PLAN = "CREATE_CORRECTIVE_PLAN"
    FAIL = "FAIL"


@dataclass(frozen=True, slots=True)
class ResolveMismatchRecoveryCommand:
    command_id: str
    request_hash: str
    run_id: str
    action_id: str
    expected_version: int
    resolution: MismatchRecoveryResolution


@dataclass(frozen=True, slots=True)
class ResolveMismatchRecoveryResult:
    applied: bool
    result_code: str
    run_id: str
    current_status: str
    current_version: int
    conflict_detail: str | None = None
    result_kind: str | None = None
    plan_id: str | None = None


class ResolveMismatchRecoveryHandler:
    """Own mismatch resolution without permitting UNKNOWN_RESULT blind resend."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int], next_id: Callable[[], str], enqueue_resume: Callable[..., None] | None = None) -> None:
        self._f = unit_of_work_factory
        self._n = now_ms
        self._next_id = next_id
        self._enqueue_resume = enqueue_resume

    @classmethod
    def from_legacy_service_supplier(cls, supplier: Callable[[], object], *, id_generator: object, coordinator: object) -> "ResolveMismatchRecoveryHandler":
        service = supplier()
        return cls(unit_of_work_factory=service._unit_of_work_factory, now_ms=service._now_ms, next_id=id_generator.next_id, enqueue_resume=coordinator.enqueue_resume)  # type: ignore[attr-defined]

    def __call__(self, command: ResolveMismatchRecoveryCommand, *, request_id: str) -> ResolveMismatchRecoveryResult:
        result = self._persist(command)
        if result.applied and result.current_status == RunStatus.PLANNING.value and result.result_kind == "CORRECTIVE_PLAN_REQUIRED" and result.plan_id is not None and self._enqueue_resume is not None:
            self._enqueue_resume(run_id=command.run_id, request_id=request_id, command_id=command.command_id, resume_kind="RECOVERY_CORRECTIVE_PLAN", resume_payload={"plan_id": result.plan_id})
        return result

    def _persist(self, command: ResolveMismatchRecoveryCommand) -> ResolveMismatchRecoveryResult:
        with self._f() as unit_of_work:
            now_ms = self._n()
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                if existing.request_hash != command.request_hash:
                    run = unit_of_work.runs.get_by_id(command.run_id)
                    return ResolveMismatchRecoveryResult(False, ResultCode.DUPLICATE_COMMAND.value, command.run_id, run.status.value if run else "UNKNOWN", run.version if run else 0, "command_id already exists with a different request_hash")
                if existing.status is CommandReceiptStatus.RECEIVED or existing.response_json is None:
                    raise RuntimeError("RECEIVED receipt requires transaction recovery before replay")
                return ResolveMismatchRecoveryResult(**loads(existing.response_json))
            run = unit_of_work.runs.get_by_id(command.run_id)
            if run is None:
                raise LookupError(f"run not found: {command.run_id}")
            action = unit_of_work.actions.get_by_id(command.action_id)
            if action is None:
                raise LookupError(f"action not found: {command.action_id}")
            plan = unit_of_work.plans.get_by_id(action.plan_id)
            if plan is None or plan.run_id != run.id:
                raise LookupError("recovery action is not owned by run")
            if command.resolution is not MismatchRecoveryResolution.FAIL and action.status != ActionStatus.MISMATCH.value:
                return self._reject(unit_of_work, command, run.status.value, run.version, plan.id, "recovery requires an immutable MISMATCH action", now_ms)
            if has_durable_cancel_intent(unit_of_work.command_receipts, run.id):
                return self._reject(unit_of_work, command, run.status.value, run.version, plan.id, "mismatch resolution requires cancel_intent_active=false", now_ms)
            next_status = {MismatchRecoveryResolution.ACCEPT_PARTIAL: RunStatus.COMPLETED, MismatchRecoveryResolution.FAIL: RunStatus.FAILED}.get(command.resolution, RunStatus.PLANNING)
            preview = transition_run(run.status, command=RunCommand.RESOLVE_RECOVERY, current_version=run.version, expected_version=command.expected_version, recovery_next_status=next_status)
            if not preview.applied:
                return self._reject(unit_of_work, command, preview.current_status.value, preview.current_version, plan.id, preview.conflict_detail, now_ms, result_code=preview.result_code.value)
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="ResolveMismatchRecovery", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=run.id, created_at_ms=now_ms)
            if command.resolution is MismatchRecoveryResolution.ACCEPT_PARTIAL:
                cancel_pending_actions(unit_of_work=unit_of_work, run_id=run.id, plan_id=plan.id, updated_at_ms=now_ms)
                unit_of_work.plans.complete(plan.id)
                result_plan, result_kind = plan.id, "PARTIAL"
            elif command.resolution is MismatchRecoveryResolution.FAIL:
                result_plan, result_kind = plan.id, "FAILED"
            else:
                for candidate in unit_of_work.actions.list_by_plan(plan.id):
                    unit_of_work.approvals.revoke_active_by_action(candidate.id)
                unit_of_work.plans.supersede(plan.id)
                revision = max(item.revision_no for item in unit_of_work.plans.list_by_run(run.id)) + 1
                corrective = PlanRecord(id=self._next_id(), run_id=run.id, revision_no=revision, status=PlanStatus.DRAFT, summary_text=f"Corrective plan for mismatch action {action.id}", created_at_ms=now_ms)
                unit_of_work.plans.insert_draft(corrective)
                result_plan, result_kind = corrective.id, "CORRECTIVE_PLAN_REQUIRED"
            resolved = unit_of_work.runs.resolve_recovery(run.id, expected_version=command.expected_version, recovery_next_status=next_status, finished_at_ms=now_ms if next_status in {RunStatus.COMPLETED, RunStatus.FAILED} else None)
            if not resolved.applied:
                raise RuntimeError("validated recovery transition was not applied")
            unit_of_work.traces.add(TraceEventRecord(run_id=run.id, action_id=action.id, event_type="RECOVERY_RESOLVED", status=resolved.current_status.value, duration_ms=None, payload_json=dumps({"resolution": command.resolution.value}, sort_keys=True), created_at_ms=now_ms))
            unit_of_work.audits.add(audit_event(run_id=run.id, action_id=action.id, event_type="RECOVERY_RESOLVED", outcome=ResultCode.TRANSITION_APPLIED.value, metadata={"resolution": command.resolution.value}, created_at_ms=now_ms))
            result = ResolveMismatchRecoveryResult(True, ResultCode.TRANSITION_APPLIED.value, run.id, resolved.current_status.value, resolved.current_version, result_kind=result_kind, plan_id=result_plan)
            self._finish(unit_of_work, command.command_id, result, now_ms)
            return result

    def _reject(self, unit_of_work: UnitOfWork, command: ResolveMismatchRecoveryCommand, status: str, version: int, plan_id: str, detail: str | None, now_ms: int, *, result_code: str = ResultCode.STATE_CONFLICT.value) -> ResolveMismatchRecoveryResult:
        unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="ResolveMismatchRecovery", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
        result = ResolveMismatchRecoveryResult(False, result_code, command.run_id, status, version, detail, plan_id=plan_id)
        self._finish(unit_of_work, command.command_id, result, now_ms)
        return result

    @staticmethod
    def _finish(unit_of_work: UnitOfWork, command_id: str, result: ResolveMismatchRecoveryResult, now_ms: int) -> None:
        unit_of_work.command_receipts.finish_json(command_id=command_id, applied=result.applied, result_code=ResultCode(result.result_code), result_version=result.current_version, response_json=dumps(asdict(result), sort_keys=True), completed_at_ms=now_ms)
        unit_of_work.commit()
