# ruff: noqa: E501
from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_constraints_and_policy_summary_node import (
    inspect_constraints_and_policy_summary_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_constraints_and_policy_summary_projection import (
    project_inspect_constraints_and_policy_summary_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_constraints_and_policy_summary import (
    route_after_inspect_constraints_and_policy_summary,
)

DIMENSION = "review.inspect_constraints_and_policy_summary"


def test_constraints_node_projects_bounded_summary_and_routes_to_aggregate() -> None:
    state = {
        "request_intent": {"constraints": []},
        "planning_result": {"schema_version": 2, "answer": "draft"},
        "policy_summary": {"allowed": True},
        "tool_route_plan": {"must_not_project": True},
    }
    assert set(project_inspect_constraints_and_policy_summary_input(state)) == {
        "request_intent",
        "planning_result",
        "policy_summary",
    }
    patch = inspect_constraints_and_policy_summary_node(
        state,
        invoke=lambda _prompt_id, _input: {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        },
    )
    assert route_after_inspect_constraints_and_policy_summary({**state, **patch}) == (
        "aggregate_findings"
    )
