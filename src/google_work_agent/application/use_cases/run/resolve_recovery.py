"""Resolve one persisted mismatch recovery decision."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps

from google_work_agent.application.cancel_intent import has_durable_cancel_intent
from google_work_agent.application.write_execution_contracts import WriteRunResponse as ResolveRecoveryResult
from google_work_agent.application.write_persistence import audit_event, cancel_pending_actions, finish_json_receipt, require_action, require_plan, require_run, resolve_existing_run_receipt
from google_work_agent.application.write_recovery_contracts import RecoveryResolutionKind, ResolveMismatchRecoveryCommand as ResolveRecoveryCommand
from google_work_agent.domain import ActionStatus, ResultCode, RunCommand, RunStatus, transition_run
from google_work_agent.ports import PlanRecord, PlanStatus, TraceEventRecord, UnitOfWork


class ResolveRecoveryHandler:
    """Own recovery state choice; never turns UNKNOWN_RESULT into a normal retry."""

    def __init__(self, *, unit_of_work_factory: Callable[[], UnitOfWork], now_ms: Callable[[], int], next_id: Callable[[], str], enqueue_resume: Callable[..., None]) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms
        self._next_id = next_id
        self._enqueue_resume = enqueue_resume

    @classmethod
    def from_legacy_service_supplier(cls, service_supplier: Callable[[], object], *, id_generator: object, coordinator: object) -> "ResolveRecoveryHandler":
        service = service_supplier()
        return cls(unit_of_work_factory=service._unit_of_work_factory, now_ms=service._now_ms, next_id=id_generator.next_id, enqueue_resume=coordinator.enqueue_resume)  # type: ignore[attr-defined]

    def __call__(self, command: ResolveRecoveryCommand, *, request_id: str) -> ResolveRecoveryResult:
        if command.resolution_kind is RecoveryResolutionKind.CREATE_CORRECTIVE_PLAN and command.corrective_plan_id is None:
            command = ResolveRecoveryCommand(command_id=command.command_id, request_hash=command.request_hash, run_id=command.run_id, action_id=command.action_id, expected_run_version=command.expected_run_version, resolution_kind=command.resolution_kind, corrective_plan_id=self._next_id())
        result = self._persist(command)
        if result.applied and result.run_status == RunStatus.PLANNING.value and result.result_kind == "CORRECTIVE_PLAN_REQUIRED" and result.plan_id is not None:
            self._enqueue_resume(run_id=command.run_id, request_id=request_id, command_id=command.command_id, resume_kind="RECOVERY_CORRECTIVE_PLAN", resume_payload={"plan_id": result.plan_id})
        return result

    def _persist(self, command: ResolveRecoveryCommand) -> ResolveRecoveryResult:
        with self._unit_of_work_factory() as unit_of_work:
            existing = unit_of_work.command_receipts.get_by_command_id(command.command_id)
            if existing is not None:
                return resolve_existing_run_receipt(unit_of_work=unit_of_work, receipt=existing, request_hash=command.request_hash, run_id=command.run_id, now_ms=self._now_ms())
            now_ms = self._now_ms()
            unit_of_work.command_receipts.add_received(command_id=command.command_id, command_type="ResolveMismatchRecovery", request_hash=command.request_hash, aggregate_type="Run", aggregate_id=command.run_id, created_at_ms=now_ms)
            run = require_run(unit_of_work, command.run_id)
            action = require_action(unit_of_work, command.action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            requires_mismatch = command.resolution_kind is not RecoveryResolutionKind.FAIL
            if plan.run_id != run.id or (requires_mismatch and action.status != ActionStatus.MISMATCH.value):
                return self._finish(unit_of_work, command.command_id, ResolveRecoveryResult(applied=False, result_code=ResultCode.STATE_CONFLICT.value, run_id=run.id, run_status=run.status.value, run_version=run.version, plan_id=plan.id, plan_status=plan.status.value, conflict_detail="recovery requires a MISMATCH action owned by the run" if requires_mismatch else "recovery requires an action owned by the run"), now_ms)
            if has_durable_cancel_intent(unit_of_work.command_receipts, run.id):
                return self._finish(unit_of_work, command.command_id, ResolveRecoveryResult(applied=False, result_code=ResultCode.STATE_CONFLICT.value, run_id=run.id, run_status=run.status.value, run_version=run.version, plan_id=plan.id, plan_status=plan.status.value, conflict_detail="recovery resolution requires cancel_intent_active=false"), now_ms)
            next_status = {RecoveryResolutionKind.ACCEPT_PARTIAL: RunStatus.COMPLETED, RecoveryResolutionKind.FAIL: RunStatus.FAILED}.get(command.resolution_kind, RunStatus.PLANNING)
            preview = transition_run(run.status, command=RunCommand.RESOLVE_RECOVERY, current_version=run.version, expected_version=command.expected_run_version, recovery_next_status=next_status)
            if not preview.applied:
                return self._finish(unit_of_work, command.command_id, ResolveRecoveryResult(applied=False, result_code=preview.result_code.value, run_id=run.id, run_status=preview.current_status.value, run_version=preview.current_version, plan_id=plan.id, plan_status=plan.status.value, conflict_detail=preview.conflict_detail), now_ms)
            if command.resolution_kind is RecoveryResolutionKind.ACCEPT_PARTIAL:
                cancel_pending_actions(unit_of_work=unit_of_work, run_id=run.id, plan_id=plan.id, updated_at_ms=now_ms)
                unit_of_work.plans.complete(plan.id)
                result_plan, result_plan_status, result_kind = plan.id, PlanStatus.COMPLETED.value, "PARTIAL"
            elif command.resolution_kind is RecoveryResolutionKind.FAIL:
                result_plan, result_plan_status, result_kind = plan.id, plan.status.value, "FAILED"
            else:
                if not command.corrective_plan_id:
                    raise ValueError("corrective_plan_id is required for CREATE_CORRECTIVE_PLAN")
                for candidate in unit_of_work.actions.list_by_plan(plan.id):
                    unit_of_work.approvals.revoke_active_by_action(candidate.id)
                unit_of_work.plans.supersede(plan.id)
                next_revision = max(item.revision_no for item in unit_of_work.plans.list_by_run(run.id)) + 1
                corrective_plan = PlanRecord(id=command.corrective_plan_id, run_id=run.id, revision_no=next_revision, status=PlanStatus.DRAFT, summary_text=f"Corrective plan for mismatch action {action.id}", created_at_ms=now_ms)
                unit_of_work.plans.insert_draft(corrective_plan)
                result_plan, result_plan_status, result_kind = corrective_plan.id, corrective_plan.status.value, "CORRECTIVE_PLAN_REQUIRED"
            resolved = unit_of_work.runs.resolve_recovery(run.id, expected_version=command.expected_run_version, recovery_next_status=next_status, finished_at_ms=now_ms if next_status in {RunStatus.COMPLETED, RunStatus.FAILED} else None)
            if not resolved.applied:
                raise RuntimeError("validated recovery transition was not applied")
            unit_of_work.traces.add(TraceEventRecord(run_id=run.id, action_id=action.id, event_type="RECOVERY_RESOLVED", status=resolved.current_status.value, duration_ms=None, payload_json=dumps({"resolution_kind": command.resolution_kind.value}, sort_keys=True), created_at_ms=now_ms))
            unit_of_work.audits.add(audit_event(run_id=run.id, action_id=action.id, event_type="RECOVERY_RESOLVED", outcome=ResultCode.TRANSITION_APPLIED.value, metadata={"resolution_kind": command.resolution_kind.value}, created_at_ms=now_ms))
            return self._finish(unit_of_work, command.command_id, ResolveRecoveryResult(applied=True, result_code=ResultCode.TRANSITION_APPLIED.value, run_id=run.id, run_status=resolved.current_status.value, run_version=resolved.current_version, plan_id=result_plan, plan_status=result_plan_status, result_kind=result_kind), now_ms)

    @staticmethod
    def _finish(unit_of_work: UnitOfWork, command_id: str, response: ResolveRecoveryResult, now_ms: int) -> ResolveRecoveryResult:
        finish_json_receipt(unit_of_work, command_id, response, response.run_version, now_ms)
        unit_of_work.commit()
        return response


__all__ = ["RecoveryResolutionKind", "ResolveRecoveryCommand", "ResolveRecoveryHandler", "ResolveRecoveryResult"]
