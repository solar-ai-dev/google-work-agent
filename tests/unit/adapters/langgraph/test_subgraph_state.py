from typing import get_type_hints

from google_work_agent.adapters.langgraph.graph_state import GraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    AcquisitionLocalState,
    ContextRetrievalLocalState,
    PlanningLocalState,
    RequestUnderstandingLocalState,
    ReviewLocalState,
    SingleWorkflowLocalState,
    WorkAnalysisLocalState,
)


def test_parent_graph_state_excludes_every_subgraph_working_field() -> None:
    parent_fields = get_type_hints(GraphState, include_extras=True)

    assert not any(field.endswith("_agent_local__") for field in parent_fields)
    assert "__request_output__" not in parent_fields
    assert "__planning_result__" not in parent_fields
    assert "__profile_request_source_output__" not in parent_fields
    assert "__profile_reason_plan_output__" not in parent_fields


def test_each_local_state_owns_only_its_subgraph_working_fields() -> None:
    cases = (
        (RequestUnderstandingLocalState, "__request_agent_local__"),
        (AcquisitionLocalState, "__acquisition_agent_local__"),
        (ContextRetrievalLocalState, "__context_agent_local__"),
        (WorkAnalysisLocalState, "__analysis_agent_local__"),
        (PlanningLocalState, "__planning_agent_local__"),
        (ReviewLocalState, "__review_agent_local__"),
        (SingleWorkflowLocalState, "__profile_agent_local__"),
    )

    for local_state, owned_field in cases:
        local_fields = get_type_hints(local_state, include_extras=True)
        assert owned_field in local_fields
        assert all(
            field == owned_field or not field.endswith("_agent_local__") for field in local_fields
        )
