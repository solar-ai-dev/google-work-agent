from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowInvocationResult,
    WorkflowOutcome,
    WorkflowResumeRequest,
    WorkflowStartRequest,
)
from tests.support.fakes import FakeWorkflowRuntime, WorkflowFailure


def test_fake_workflow_runtime_records_calls_and_returns_queued_results() -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="answer-only",
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"status": "started"},
        )
    )

    result = runtime.start(
        WorkflowStartRequest(
            run_id="run-1",
            conversation_id="conversation-1",
            workflow_key="answer-only",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            request_text="hello",
            selected_resource_ids=(),
            correlation=WorkflowCorrelationContext(
                request_id="request-1",
                command_id="cmd-1",
                api_contract_version="1",
            ),
        )
    )

    assert result.payload["status"] == "started"
    assert runtime.call_log[0].operation == "start"


def test_fake_workflow_runtime_enforces_run_binding_and_failure_queue() -> None:
    runtime = FakeWorkflowRuntime()
    runtime.queue_failure(WorkflowFailure(message="boom"))

    try:
        runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="flow-a",
                resume_kind="manual",
                resume_payload={},
                correlation=WorkflowCorrelationContext(
                    request_id="request-1",
                    command_id="resume-1",
                    api_contract_version="1",
                ),
            )
        )
    except RuntimeError as error:
        assert "boom" in str(error)
    else:
        raise AssertionError("expected workflow failure")

    runtime.queue_result(
        WorkflowInvocationResult(
            run_id="run-1",
            workflow_key="flow-a",
            outcome=WorkflowOutcome.ACCEPTED,
            payload={"ok": True},
        )
    )
    runtime.resume(
        WorkflowResumeRequest(
            run_id="run-1",
            workflow_key="flow-a",
            resume_kind="manual",
            resume_payload={},
            correlation=WorkflowCorrelationContext(
                request_id="request-2",
                command_id="resume-2",
                api_contract_version="1",
            ),
        )
    )

    try:
        runtime.resume(
            WorkflowResumeRequest(
                run_id="run-1",
                workflow_key="flow-b",
                resume_kind="manual",
                resume_payload={},
                correlation=WorkflowCorrelationContext(
                    request_id="request-3",
                    command_id="resume-3",
                    api_contract_version="1",
                ),
            )
        )
    except RuntimeError as error:
        assert "already bound" in str(error)
    else:
        raise AssertionError("expected workflow key binding failure")
