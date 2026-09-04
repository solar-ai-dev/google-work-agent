from google_work_agent.adapters.langgraph.main.action_evidence_projection import (
    project_current_action_evidence,
)
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_current_action_evidence__projects_persisted__user_message_identity() -> None:
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="LOCAL_GPU",
        request_text="Create the exact event.",
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext("request-1", "command-1", "v1"),
        user_message_id="message-1",
    )

    result = project_current_action_evidence(
        state={"run_id": "run-1", "retrieval_result": None, "__request__": request},
        evidence_store=object(),
    )

    assert result == [
        {
            "schema_version": 1,
            "evidence_id": "message-1",
            "origin_type": "USER_MESSAGE",
            "message_id": "message-1",
            "kind": "USER_REQUEST",
            "excerpt": "Create the exact event.",
        }
    ]
