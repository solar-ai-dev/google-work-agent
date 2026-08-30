# ruff: noqa: E501
from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.projections.recheck_affected_dimensions_projection import (
    project_recheck_affected_dimensions_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_recheck_affected_dimensions import (
    route_after_recheck_affected_dimensions,
)


def test_recheck_projection_and_router_are_exact() -> None:
    state = {
        "affected_dimensions": ["review.inspect_goal_and_evidence"],
        "affected_action_ids": [],
        "affected_route_ids": [],
        "request_intent": {},
        "tool_route_plan": {},
        "planning_result": {},
        "work_analysis": {},
        "evidence": [],
        "policy_summary": {},
        "confirmation_response": {},
        "prior_review_findings": [{"code": "must-not-cross"}],
    }
    projected = project_recheck_affected_dimensions_input(state)
    assert "prior_review_findings" not in projected
    assert set(projected) == set(state) - {"prior_review_findings"}
    assert (
        route_after_recheck_affected_dimensions({"affected_dimension_recheck": {}})
        == "aggregate_findings"
    )
    assert route_after_recheck_affected_dimensions({"__target__": "end"}) == "end"
