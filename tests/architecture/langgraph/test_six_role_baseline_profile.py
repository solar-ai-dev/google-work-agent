"""SIX_ROLE_BASELINE composition contract."""

from tests.architecture.langgraph.profile_test_support import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.six_role_baseline import (
    SEMANTIC_OWNER_BINDINGS,
    build_six_role_baseline_graph,
)


def test_six_profile_has_six_physical_subgraphs_and_six_semantic_owners() -> None:
    arguments = profile_build_arguments()
    semantic_owners = arguments.pop("semantic_owners")
    composition = build_six_role_baseline_graph(**arguments)

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
