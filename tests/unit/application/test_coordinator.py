from __future__ import annotations

import time
from dataclasses import dataclass

import pytest
from tests.support.fakes import FakeWorkflowRuntime

from google_work_agent.adapters.events.in_memory import InMemoryRunEventPublisher
from google_work_agent.application.coordinator import LocalRunCoordinator
from google_work_agent.application.queries import OpenRunRecord, RunExecutionContext
from google_work_agent.ports import WorkflowInvocationResult, WorkflowOutcome


@dataclass
class _QueryStub:
    status: str

    def list_open_runs(self) -> tuple[OpenRunRecord, ...]:
        return (
            OpenRunRecord(
                run_id="run-1",
                workflow_key="thread-1",
                status=self.status,
                version=3,
            ),
        )

    def get_run_execution_context(self, run_id: str) -> RunExecutionContext:
        assert run_id == "run-1"
        return RunExecutionContext(
            run_id=run_id,
            conversation_id="conversation-1",
            workflow_key="thread-1",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            status=self.status,
            version=3,
            request_text="Recover the open run.",
            selected_resource_ids=(),
        )


@pytest.mark.parametrize(
    "status",
    ["WAITING_CONFIRMATION", "WAITING_APPROVAL", "VERIFYING", "RECOVERY_REQUIRED"],
)
def test_startup_reconciles_every_recoverable_open_run(status: str) -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="thread-1",
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"phase": status},
        )
    )
    coordinator = LocalRunCoordinator(
        query_service=_QueryStub(status),  # type: ignore[arg-type]
        unit_of_work_factory=lambda: None,  # type: ignore[arg-type,return-value]
        workflow_runtime=runtime,
        event_publisher=InMemoryRunEventPublisher(
            service_instance_id="service-1",
            capacity_per_run=8,
        ),
        now_ms=lambda: 1000,
        api_contract_version="1",
    )

    coordinator.start()
    deadline = time.time() + 1
    while not runtime.call_log and time.time() < deadline:
        time.sleep(0.01)
    coordinator.stop()

    assert len(runtime.call_log) == 1
    assert runtime.call_log[0].operation == "recover_open_run"
    assert runtime.call_log[0].payload == {"domain_status": status, "domain_version": 3}
