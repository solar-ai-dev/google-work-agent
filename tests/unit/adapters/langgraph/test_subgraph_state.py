from typing import get_type_hints

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    AcquisitionLocalState,
    ContextRetrievalInputState,
    ContextRetrievalLocalState,
    PlanningInputState,
    PlanningLocalState,
    RequestUnderstandingInputState,
    ReviewInputState,
    ReviewLocalState,
    SingleWorkflowLocalState,
    ToolRoutingInputState,
    WorkAnalysisInputState,
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


def test_native_role_input_projections_are_narrower_than_main_graph_state() -> None:
    main_fields = set(get_type_hints(GraphState, include_extras=True))
    projections = (
        RequestUnderstandingInputState,
        ToolRoutingInputState,
        ContextRetrievalInputState,
        WorkAnalysisInputState,
        PlanningInputState,
        ReviewInputState,
    )

    for projection in projections:
        projection_fields = set(get_type_hints(projection, include_extras=True))
        assert projection_fields < main_fields
        assert not any(field.endswith("_agent_local__") for field in projection_fields)


def test_role_input_projection_does_not_expose_foreign_business_artifacts() -> None:
    request_fields = set(get_type_hints(RequestUnderstandingInputState, include_extras=True))
    tool_fields = set(get_type_hints(ToolRoutingInputState, include_extras=True))
    retrieval_fields = set(get_type_hints(ContextRetrievalInputState, include_extras=True))
    analysis_fields = set(get_type_hints(WorkAnalysisInputState, include_extras=True))
    planning_fields = set(get_type_hints(PlanningInputState, include_extras=True))
    review_fields = set(get_type_hints(ReviewInputState, include_extras=True))

    assert "request_intent" not in request_fields
    assert "retrieval_result" not in request_fields
    assert "analysis_result" not in request_fields
    assert "plan_draft" not in request_fields

    assert "request_intent" in tool_fields
    assert "retrieval_result" not in tool_fields
    assert "analysis_result" not in tool_fields
    assert "plan_draft" not in tool_fields

    assert {"request_intent", "tool_route_plan", "retrieval_result"} <= retrieval_fields
    assert "analysis_result" not in retrieval_fields
    assert "plan_draft" not in retrieval_fields
    assert "plan_review" not in retrieval_fields

    assert {"request_intent", "tool_route_plan", "retrieval_result"} <= analysis_fields
    assert "plan_draft" not in analysis_fields
    assert "plan_review" not in analysis_fields

    assert {
        "request_intent",
        "tool_route_plan",
        "retrieval_result",
        "work_analysis_result",
        "answer_draft",
        "plan_draft",
        "plan_review",
    } <= planning_fields
    assert "execution_summary" not in planning_fields
    assert "verification_summary" not in planning_fields

    assert {
        "request_intent",
        "tool_route_plan",
        "retrieval_result",
        "analysis_result",
        "answer_draft",
        "plan_draft",
        "plan_review",
    } <= review_fields
    assert "execution_summary" not in review_fields
    assert "verification_summary" not in review_fields
