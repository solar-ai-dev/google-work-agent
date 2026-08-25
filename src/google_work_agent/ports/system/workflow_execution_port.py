"""Background workflow execution admission boundary."""

from typing import Protocol

from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    WorkflowExecutionSubmissionV2,
)


class WorkflowExecutionPort(Protocol):
    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1: ...

    def begin_shutdown(self) -> None: ...

    def await_drained(self, deadline_ms: int) -> bool: ...
