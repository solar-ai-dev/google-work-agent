"""Canonical Main Graph state ownership and binding closure."""

from typing import get_type_hints

from google_work_agent.adapters.langgraph.main import state as state_module
from google_work_agent.adapters.langgraph.main.state import (
    MultiAgentGraphStateV2,
    initial_graph_state,
)
from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.application.use_cases.run.guard_run_budget import build_default_run_budget
from google_work_agent.ports.system.contracts.workflow_execution import (
    WorkflowCorrelationContext,
    WorkflowStartRequest,
)


def test_main_state_has_exact_v2_owner_and_no_retrieval_scratch_fields() -> None:
    fields = set(get_type_hints(MultiAgentGraphStateV2))

    assert not hasattr(state_module, "ProductionGraphStateV2")
    assert {"graph_profile", "graph_version", "langgraph_thread_id", "run_input"} <= fields
    assert {
        "context_bundle",
        "context_result",
        "evidence_drafts",
        "llm_provider_result",
    }.isdisjoint(fields)


def test_initial_state_pins_profile_version_and_immutable_run_input() -> None:
    request = WorkflowStartRequest(
        run_id="run-1",
        conversation_id="conversation-1",
        workflow_key="thread-1",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text="Summarize my work.",
        selected_resource_ids=(),
        run_budget=build_default_run_budget(),
        correlation=WorkflowCorrelationContext("request-1", None, "1"),
    )

    state = initial_graph_state(
        request,
        graph_profile=GraphProfile.THREE_STAGE,
        graph_version="graph-v1",
        initial_target="stage_one",
    )

    assert state["schema_version"] == 2
    assert state["graph_profile"] == "THREE_STAGE"
    assert state["graph_version"] == "graph-v1"
    assert state["langgraph_thread_id"] == "thread-1"
    assert state["run_input"]["user_request"] == "Summarize my work."
    assert "context_result" not in state
