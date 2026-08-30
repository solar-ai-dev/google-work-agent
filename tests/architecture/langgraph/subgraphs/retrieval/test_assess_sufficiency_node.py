from pathlib import Path

from google_work_agent.adapters.langgraph.subgraphs.retrieval.routing.route_after_assess_sufficiency import (  # noqa: E501
    route_after_assess_sufficiency,
)


def test_assess_sufficiency_has_exact_node_projection_and_bounded_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    node = (owner / "nodes/assess_sufficiency_node.py").read_text()
    assert "project_assess_sufficiency_input" in node
    assert (owner / "projections/assess_sufficiency_projection.py").exists()
    router = (owner / "routing/route_after_assess_sufficiency.py").read_text()
    assert 'return "plan_query"' in router
    assert 'return "finalize"' in router


def test_assess_sufficiency_router_preserves_frozen_route_and_three_round_bound() -> None:
    state = {
        "sufficiency": {"status": "NEEDS_MORE_DATA"},
        "tool_route_plan": {"input_plan": {}},
        "read_result_handles": ["read-1"],
        "query_attempts": [{"round_no": 0}, {"round_no": 1}],
    }

    assert route_after_assess_sufficiency(state) == "plan_query"
    assert (
        route_after_assess_sufficiency(
            {**state, "query_attempts": [*state["query_attempts"], {"round_no": 2}]}
        )
        == "finalize"
    )
    assert route_after_assess_sufficiency({**state, "tool_route_plan": None}) == "finalize"
    assert route_after_assess_sufficiency({**state, "read_result_handles": []}) == "finalize"
