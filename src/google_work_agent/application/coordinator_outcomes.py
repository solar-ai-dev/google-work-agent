"""Persist and publish outcomes produced by the local run coordinator."""

from __future__ import annotations

from collections.abc import Callable

from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
    ProjectRunEventHandler,
)
from google_work_agent.application.write_execution_contracts import WriteRunResponse
from google_work_agent.domain.recovery.transitions.require_recovery import (
    transition_require_recovery,
)
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports import (
    UnitOfWork,
    WorkflowOutcome,
)


class RunOutcomeHandler:
    """Own domain persistence and projection publication for runtime outcomes."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        project_run_event: ProjectRunEventHandler,
        now_ms: Callable[[], int],
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._project_run_event = project_run_event
        self._now_ms = now_ms

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
            with self._unit_of_work_factory() as unit_of_work:
                run = unit_of_work.runs.get(run_id)
                if run is None:
                    raise LookupError(f"run not found: {run_id}")
                next_status = transition_require_recovery(run.status)
                if not unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {"status": next_status.value, "version": run.version + 1},
                ):
                    raise RuntimeError("validated RequireRecovery CAS failed")
                unit_of_work.commit()
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
            with self._unit_of_work_factory() as unit_of_work:
                run = unit_of_work.runs.get(run_id)
                if run is None:
                    raise LookupError(f"run not found: {run_id}")
                if run.version != expected_version:
                    raise RuntimeError("workflow outcome Run version conflict")
                next_status = transition_require_recovery(run.status)
                if not unit_of_work.runs.update_if_version_and_status(
                    run.id,
                    run.version,
                    frozenset({run.status}),
                    {"status": next_status.value, "version": run.version + 1},
                ):
                    raise RuntimeError("validated failed-outcome RequireRecovery CAS failed")
                unit_of_work.commit()
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
