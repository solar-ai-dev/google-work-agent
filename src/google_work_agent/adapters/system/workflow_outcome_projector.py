"""Translate workflow-driver outcomes into exact Application operations."""

from __future__ import annotations

from collections.abc import Callable, Mapping

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
from google_work_agent.domain.recovery.model import RECOVERY_RESOLUTION_MATRIX, RecoveryReasonV1
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowOutcome
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RegisteredResumeTargetRefV2,
)
from google_work_agent.ports.system.sse_event_buffer_port import RunSseEventTypeV1


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
        if response.run_status == RunStatusV1.CANCELLED.value:
            self._publish(
                response.run_id,
                "completed",
                {"status": "CANCELLED", "result_kind": "CANCELLED"},
            )
            return
        self._publish(
            response.run_id,
            "run_status",
            {"status": response.run_status, "snapshot_version": response.run_version},
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
            self._publish(run_id, "recovery_required", _recovery_payload("CHECKPOINT_MISMATCH"))
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
        event_payload = _canonical_payload(event_type, payload, expected_version)
        if event_payload is not None:
            self._publish(run_id, event_type, event_payload)

    def publish(self, event: ProjectRunEventCommand) -> None:
        try:
            self._project_run_event(event)
        except Exception:
            return

    def _publish(
        self,
        run_id: str,
        event_type: RunSseEventTypeV1,
        payload: dict[str, object],
    ) -> None:
        self.publish(
            ProjectRunEventCommand(
                run_id=run_id,
                occurred_at_ms=self._now_ms(),
                event_type=event_type,
                payload=payload,
            )
        )

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


def accepted_event_type(payload: dict[str, object]) -> RunSseEventTypeV1:
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


def _canonical_payload(
    event_type: RunSseEventTypeV1,
    payload: Mapping[str, object],
    snapshot_version: int,
) -> dict[str, object] | None:
    if event_type == "run_status" and isinstance(payload.get("run_status"), str):
        return {"status": payload["run_status"], "snapshot_version": snapshot_version}
    if event_type == "phase_changed" and isinstance(payload.get("phase"), str):
        return {"phase": payload["phase"]}
    if event_type == "error":
        error_code = payload.get("error_code")
        return {
            "error_code": error_code if isinstance(error_code, str) else "WORKFLOW_FAILED",
            "recoverable": True,
        }
    interrupt = payload.get("user_interrupt")
    if event_type == "confirmation_required" and isinstance(interrupt, Mapping):
        interrupt_id, question, options = (
            interrupt.get("interrupt_id"),
            interrupt.get("question"),
            interrupt.get("options"),
        )
        if (
            isinstance(interrupt_id, str)
            and isinstance(question, str)
            and isinstance(options, list)
        ):
            labels = [item.get("label") for item in options if isinstance(item, Mapping)]
            if all(isinstance(label, str) for label in labels):
                return {"interrupt_id": interrupt_id, "question": question, "options": labels}
    if event_type == "approval_required" and isinstance(interrupt, Mapping):
        action_ids = interrupt.get("action_ids")
        if isinstance(action_ids, list) and all(isinstance(item, str) for item in action_ids):
            return {"action_ids": action_ids}
    return None


def _recovery_payload(reason: RecoveryReasonV1) -> dict[str, object]:
    return {
        "recovery": {
            "reason_code": reason,
            "target": {"target_kind": "RUN"},
            "allowed_resolution_kinds": [
                item.value for item in RECOVERY_RESOLUTION_MATRIX[reason]
            ],
        }
    }
