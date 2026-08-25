from __future__ import annotations

from threading import Event

from google_work_agent.adapters.system.workflow_handoff_reconciliation_loop import (
    WorkflowHandoffReconciliationLoop,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsResult,
)


def test_live_loop_only_drives_injected_application_reconciler() -> None:
    called = Event()
    commands: list[RedriveWorkflowHandoffsCommand] = []

    def redrive(command: RedriveWorkflowHandoffsCommand) -> RedriveWorkflowHandoffsResult:
        commands.append(command)
        called.set()
        return RedriveWorkflowHandoffsResult(0, 0, 0)

    loop = WorkflowHandoffReconciliationLoop(
        redrive=redrive,  # type: ignore[arg-type]
        interval_seconds=60,
        batch_limit=7,
    )
    try:
        loop.start()
        assert called.wait(1)
    finally:
        loop.stop()
    assert commands[0].limit == 7
