"""SIX_ROLE_BASELINE composition contract."""

from tests.support.langgraph_profile import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.six_role_baseline import (
    SEMANTIC_OWNER_BINDINGS,
    build_six_role_baseline_graph,
)


def test_six_profile_has_six_physical_subgraphs_and_six_semantic_owners() -> None:
    bindings, controls, route_next_node, checkpointer, semantic_owners = profile_build_arguments()
    composition = build_six_role_baseline_graph(
        bindings=bindings,
        control_bindings=controls,
        route_next_node=route_next_node,
        checkpointer=checkpointer,
    )

    assert tuple(composition.native_subgraphs()) == (
        "request_understanding",
        "tool_route",
        "context_retriever",
        "work_analysis",
        "planning",
        "review",
    )
    assert len(set(SEMANTIC_OWNER_BINDINGS.values())) == 6
    assert set(SEMANTIC_OWNER_BINDINGS) == semantic_owners
