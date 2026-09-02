from __future__ import annotations

from google_work_agent.adapters.langgraph.subgraphs.review.nodes import (
    inspect_constraints_and_policy_summary_node as constraints_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections import (
    inspect_constraints_and_policy_summary_projection as constraints_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing import (
    route_after_inspect_constraints_and_policy_summary as constraints_route,
)

DIMENSION = "review.inspect_constraints_and_policy_summary"


def test_constraints_node_projects__bounded_summary_and__routes_to_aggregate() -> None:
    state = {
        "request_intent": {"constraints": []},
        "planning_result": {"schema_version": 2, "answer": "draft"},
        "policy_summary": {"allowed": True},
        "tool_route_plan": {"must_not_project": True},
    }
    assert set(
        constraints_projection.project_inspect_constraints_and_policy_summary_input(state)
    ) == {
        "request_intent",
        "planning_result",
        "policy_summary",
    }
    patch = constraints_node.inspect_constraints_and_policy_summary_node(
        state,
        invoke=lambda _prompt_id, _input: {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        },
    )
    assert constraints_route.route_after_inspect_constraints_and_policy_summary(
        {**state, **patch}
    ) == ("aggregate_findings")
