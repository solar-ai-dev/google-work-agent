"""Persist and publish outcomes produced by the local run coordinator."""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.projections import build_projection_event
from google_work_agent.application.write_actions import WriteRunResponse
from google_work_agent.domain import RunStatus
from google_work_agent.ports import (
    PendingProjectionEvent,
    SseEventBufferPort,
    UnitOfWork,
    WorkflowOutcome,
)


class RunOutcomeHandler:
    """Own domain persistence and projection publication for runtime outcomes."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        event_publisher: SseEventBufferPort,
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._event_publisher = event_publisher
        self._now_ms = now_ms

    def publish_cancel_response(self, response: WriteRunResponse) -> None:
        event_type = (
            "completed"
            if response.run_status == RunStatus.CANCELLED.value
            else "recovery_required"
            if response.run_status == RunStatus.RECOVERY_REQUIRED.value
            else "run_status"
        )
        self.publish(
            build_projection_event(
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
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.runs.set_recovery_required(run_id, finished_at_ms=None)
                unit_of_work.commit()
            self.publish(
                build_projection_event(
                    run_id=run_id,
                    occurred_at_ms=self._now_ms(),
                    event_type="recovery_required",
                    payload={"outcome": outcome.value},
                )
            )
            return
        if outcome is WorkflowOutcome.FAILED:
            with self._unit_of_work_factory() as unit_of_work:
                unit_of_work.runs.fail_run(
                    run_id,
                    expected_version=expected_version,
                    finished_at_ms=self._now_ms(),
                )
                unit_of_work.commit()
        event_type = {
            WorkflowOutcome.ACCEPTED: accepted_event_type(payload),
            WorkflowOutcome.ALREADY_RUNNING: "phase_changed",
            WorkflowOutcome.COMPLETED: "completed",
            WorkflowOutcome.RECOVERY_REQUIRED: "recovery_required",
            WorkflowOutcome.FAILED: "error",
        }[outcome]
        self.publish(
            build_projection_event(
                run_id=run_id,
                occurred_at_ms=self._now_ms(),
                event_type=event_type,
                payload={"outcome": outcome.value, **payload},
            )
        )

    def publish(self, event: PendingProjectionEvent) -> None:
        try:
            self._event_publisher.publish(event)
        except Exception:
            return


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
