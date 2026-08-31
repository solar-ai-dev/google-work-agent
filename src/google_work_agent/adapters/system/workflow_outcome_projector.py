"""Translate workflow-driver outcomes into exact Application operations."""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteRunResponse,
)
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.domain.recovery.model import RecoveryReasonV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowOutcome
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RegisteredResumeTargetRefV2,
)


class WorkflowOutcomeProjector:
    """Pure driver translation; lifecycle semantics stay in exact handlers."""

    def __init__(
        self,
        *,
        require_recovery: RequireRecoveryHandler,
        project_run_event: ProjectRunEventHandler,
        now_ms: Callable[[], int],
        id_factory: Callable[[], str],
        recovery_target: Callable[[str], RegisteredResumeTargetRefV2 | None],
    ) -> None:
        self._require_recovery = require_recovery
        self._project_run_event = project_run_event
        self._now_ms = now_ms
        self._id_factory = id_factory
        self._recovery_target = recovery_target

    def publish_cancel_response(self, response: WriteRunResponse) -> None:
        event_type = (
            "completed"
            if response.run_status == RunStatusV1.CANCELLED.value
            else "recovery_required"
            if response.run_status == RunStatusV1.RECOVERY_REQUIRED.value
            else "run_status"
        )
        self.publish(
            ProjectRunEventCommand(
                run_id=response.run_id,
                occurred_at_ms=self._now_ms(),
                event_type=event_type,
                payload={
                    "result_code": response.result_code,
                    "run_status": response.run_status,
                    "run_version": response.run_version,
                    "result_kind": response.result_kind,
                },
            )
        )

    def handle_result(
        self,
        run_id: str,
        outcome: WorkflowOutcome,
        payload: dict[str, object],
        expected_version: int,
    ) -> None:
        if outcome in {
            WorkflowOutcome.CHECKPOINT_MISSING,
            WorkflowOutcome.DOMAIN_CHECKPOINT_CONFLICT,
        }:
            self._require_recovery_result(
                run_id=run_id,
                expected_version=expected_version,
                reason="CHECKPOINT_MISMATCH",
            )
            self.publish(
                ProjectRunEventCommand(
                    run_id=run_id,
                    occurred_at_ms=self._now_ms(),
                    event_type="recovery_required",
                    payload={"outcome": outcome.value},
                )
            )
            return
        if outcome is WorkflowOutcome.FAILED:
            self._require_recovery_result(
                run_id=run_id,
                expected_version=expected_version,
                reason="CONTRACT_VIOLATION",
            )
        event_type = {
            WorkflowOutcome.ACCEPTED: accepted_event_type(payload),
            WorkflowOutcome.ALREADY_RUNNING: "phase_changed",
            WorkflowOutcome.COMPLETED: "completed",
            WorkflowOutcome.RECOVERY_REQUIRED: "recovery_required",
            WorkflowOutcome.FAILED: "error",
        }[outcome]
        self.publish(
            ProjectRunEventCommand(
                run_id=run_id,
                occurred_at_ms=self._now_ms(),
                event_type=event_type,
                payload={"outcome": outcome.value, **payload},
            )
        )

    def publish(self, event: ProjectRunEventCommand) -> None:
        try:
            self._project_run_event(event)
        except Exception:
            return

    def _require_recovery_result(
        self,
        *,
        run_id: str,
        expected_version: int,
        reason: RecoveryReasonV1,
    ) -> None:
        target = self._recovery_target(run_id) if reason == "CHECKPOINT_MISMATCH" else None
        payload = {
            "run_id": run_id,
            "expected_version": expected_version,
            "reason": reason,
        }
        result = self._require_recovery(
            RequireRecoveryCommand(
                run_id=run_id,
                expected_version=expected_version,
                command_id=self._id_factory(),
                request_hash=calculate_canonical_json_hash(payload),
                reason=reason,
                scope="RUN",
                recovery_fingerprint=calculate_canonical_json_hash(payload),
                registered_resume_target=target,
                contract_or_checkpoint_fingerprint=calculate_canonical_json_hash(payload),
            )
        )
        if not result.applied:
            raise RuntimeError(result.conflict_detail or "RequireRecovery was not applied")


def accepted_event_type(payload: dict[str, object]) -> str:
    interrupt_payload = payload.get("user_interrupt")
    if isinstance(interrupt_payload, dict):
        interrupt_kind = interrupt_payload.get("interrupt_kind")
        if interrupt_kind == "CONFIRMATION":
            return "confirmation_required"
        if interrupt_kind == "APPROVAL":
            return "approval_required"
    phase = payload.get("phase")
    if phase == "WAITING_CONFIRMATION":
        return "confirmation_required"
    if phase == "WAITING_APPROVAL":
        return "approval_required"
    return "run_status"
