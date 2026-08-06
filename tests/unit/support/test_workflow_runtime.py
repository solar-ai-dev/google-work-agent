from google_work_agent.ports import WorkflowInvocationResult
from tests.support.fakes import FakeWorkflowRuntime, WorkflowFailure


def test_fake_workflow_runtime_records_calls_and_returns_queued_results() -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="answer-only",
            payload={"status": "started"},
        )
    )

    result = runtime.start(
        run_id="run-1", workflow_key="answer-only", payload={"command_id": "cmd-1"}
    )

    assert result.payload["status"] == "started"
    assert runtime.call_log[0].operation == "start"


def test_fake_workflow_runtime_enforces_run_binding_and_failure_queue() -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_failure(WorkflowFailure(message="boom"))

    try:
        runtime.resume(run_id="run-1", workflow_key="flow-a", payload={})
    except RuntimeError as error:
        assert "boom" in str(error)
    else:
        raise AssertionError("expected workflow failure")

    runtime.queue_result(
        WorkflowInvocationResult(run_id="run-1", workflow_key="flow-a", payload={"ok": True})
    )
    runtime.resume(run_id="run-1", workflow_key="flow-a", payload={})

    try:
        runtime.resume(run_id="run-1", workflow_key="flow-b", payload={})
    except RuntimeError as error:
        assert "already bound" in str(error)
    else:
        raise AssertionError("expected workflow key binding failure")
