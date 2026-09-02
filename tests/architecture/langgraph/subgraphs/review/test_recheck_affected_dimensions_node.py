from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    recheck_affected_dimensions_projection as recheck_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing import (
    route_after_recheck_affected_dimensions as recheck_route,
)


def test_recheck_projection__and_router__are_exact() -> None:
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
    projected = recheck_projection.project_recheck_affected_dimensions_input(state)
    assert "prior_review_findings" not in projected
    assert set(projected) == set(state) - {"prior_review_findings"}
    assert (
        recheck_route.route_after_recheck_affected_dimensions({"affected_dimension_recheck": {}})
        == "aggregate_findings"
    )
    assert recheck_route.route_after_recheck_affected_dimensions({"__target__": "end"}) == "end"
