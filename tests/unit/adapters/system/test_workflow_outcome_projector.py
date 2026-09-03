from google_work_agent.adapters.system.workflow_outcome_projector import (
    WorkflowOutcomeProjector,
)
from google_work_agent.application.use_cases.sse_event.project_run_event import (
    ProjectRunEventCommand,
)
from google_work_agent.ports.system.contracts.workflow_execution import WorkflowOutcome


def test_waiting_approval_without_action_projection__publishes_run_status__for_snapshot_refresh(
) -> None:
    published: list[ProjectRunEventCommand] = []
    projector = WorkflowOutcomeProjector(
        require_recovery=lambda _command: None,  # type: ignore[arg-type]
        project_run_event=published.append,  # type: ignore[arg-type]
        now_ms=lambda: 10,
        id_factory=lambda: "event-1",
        recovery_target=lambda _run_id: None,
    )

    projector.handle_result(
        "run-1",
        WorkflowOutcome.ACCEPTED,
        {
            "phase": "WAITING_APPROVAL",
            "run_status": "WAITING_APPROVAL",
            "user_interrupt": {
                "interrupt_kind": "APPROVAL",
                "run_id": "run-1",
                "plan_id": "plan-1",
            },
        },
        4,
    )

    assert len(published) == 1
    event = published[0]
    assert event.event_type == "run_status"
    assert event.payload == {
        "status": "WAITING_APPROVAL",
        "snapshot_version": 4,
    }
