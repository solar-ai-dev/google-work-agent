from __future__ import annotations

import inspect

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import PlanningSubgraph
from google_work_agent.adapters.langgraph.subgraphs.planning.nodes.outline_answer_node import (
    outline_answer_node,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    outline_answer_projection,
)
from google_work_agent.adapters.langgraph.subgraphs.planning.routing import (
    route_after_outline_answer as outline_answer_routing,
)


def test_outline_exact_node__projection_router_and__no_branch_node() -> None:
    graph_source = inspect.getsource(PlanningSubgraph.build)
    assert 'graph.add_node("outline_answer"' in graph_source
    assert 'graph.add_node("compose_answer"' in graph_source
    assert "choose_answer_or_action_from_route_node" not in graph_source
    assert callable(outline_answer_node)
    assert callable(outline_answer_projection.project_outline_answer_input)
    assert (
        outline_answer_routing.route_after_outline_answer({"answer_outline": {}})
        == "compose_answer"
    )


def test_outline_projection__excludes_route_provider__and_history_material() -> None:
    projected = outline_answer_projection.project_outline_answer_input(
        {
            "user_request": "Summarize.",
            "request_intent": {"goal": "summary"},
            "evidence": [],
            "tool_route_plan": {"secret": "not prompt input"},
            "provider_response": {"raw": True},
            "previous_run": {"answer": "old"},
        }
    )
    assert set(projected) == {"user_request", "request_intent", "evidence"}
