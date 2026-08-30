# ruff: noqa: E501
from __future__ import annotations

import pytest

from google_work_agent.adapters.langgraph.subgraphs.review.nodes.inspect_action_scope_and_route_node import (
    inspect_action_scope_and_route_node,
)
from google_work_agent.adapters.langgraph.subgraphs.review.projections.inspect_action_scope_and_route_projection import (
    project_inspect_action_scope_and_route_input,
)
from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_action_scope_and_route import (
    route_after_inspect_action_scope_and_route,
)

DIMENSION = "review.inspect_action_scope_and_route"


def test_action_node_projection_and_policy_router_are_exact() -> None:
    state = {
        "request_intent": {},
        "tool_route_plan": {"output_plan": {"output_routes": []}},
        "planning_result": {"schema_version": 2, "actions": []},
        "evidence": [],
        "policy_summary": {},
    }
    assert set(project_inspect_action_scope_and_route_input(state)) == {
        "request_intent",
        "tool_route_plan",
        "planning_result",
        "evidence",
    }
    patch = inspect_action_scope_and_route_node(
        state,
        invoke=lambda _prompt_id, _input: {
            "schema_version": 1,
            "dimension": DIMENSION,
            "findings": [],
        },
    )
    assert route_after_inspect_action_scope_and_route({**state, **patch}) == (
        "inspect_constraints_policy"
    )


def test_action_projection_fails_closed_for_answer_artifact() -> None:
    with pytest.raises(ValueError, match="ACTION Planning artifact"):
        project_inspect_action_scope_and_route_input(
            {
                "request_intent": {},
                "tool_route_plan": {},
                "planning_result": {"answer": "done"},
                "evidence": [],
            }
        )


def test_goal_router_selects_action_inspector_only_for_action_artifact() -> None:
    state = {
        "goal_evidence_result": {
            "dimension": "review.inspect_goal_and_evidence",
        },
        "planning_result": {"schema_version": 2, "actions": []},
    }
    from google_work_agent.adapters.langgraph.subgraphs.review.routing.route_after_inspect_goal_and_evidence import (
        route_after_inspect_goal_and_evidence,
    )

    assert route_after_inspect_goal_and_evidence(state) == "inspect_action_scope_route"
