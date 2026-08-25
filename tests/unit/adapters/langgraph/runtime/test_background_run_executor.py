from __future__ import annotations

from threading import Event

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowExecutionSubmissionV2,
)


def test_same_admission_replay_is_idempotently_accepted_without_second_worker_entry() -> None:
    executed: list[str] = []
    completed = Event()

    def execute(admission: WorkflowExecutionAdmissionV1) -> None:
        executed.append(admission.admission_id)
        completed.set()

    adapter = BackgroundRunExecutorAdapter(execute_admission=execute)
    try:
        submission = WorkflowExecutionSubmissionV2(2, _admission("a-1", "r-1"))
        assert adapter.submit(submission).reason_code == "ACCEPTED"
        assert adapter.submit(submission).reason_code == "ACCEPTED"
        assert completed.wait(1)
        assert adapter.await_drained(1000)
        assert executed == ["a-1"]
    finally:
        adapter.close()


def test_different_admission_for_active_run_is_not_accepted() -> None:
    release = Event()
    started = Event()

    def execute(admission: WorkflowExecutionAdmissionV1) -> None:
        started.set()
        release.wait(1)

    adapter = BackgroundRunExecutorAdapter(execute_admission=execute)
    try:
        assert adapter.submit(WorkflowExecutionSubmissionV2(2, _admission("a-1", "r-1"))).accepted
        assert started.wait(1)
        result = adapter.submit(WorkflowExecutionSubmissionV2(2, _admission("a-2", "r-1")))
        assert not result.accepted
        assert result.reason_code == "ALREADY_RUNNING"
    finally:
        release.set()
        adapter.close()


def _admission(admission_id: str, run_id: str) -> WorkflowExecutionAdmissionV1:
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id=admission_id,
        handoff_id=f"h-{admission_id}",
        handoff_run_sequence=1,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id=run_id,
            langgraph_thread_id=f"t-{run_id}",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=0,
    )
