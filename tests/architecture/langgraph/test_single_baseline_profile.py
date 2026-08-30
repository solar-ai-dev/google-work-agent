"""SINGLE_BASELINE composition contract."""

from tests.architecture.langgraph.profile_test_support import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.single_baseline import (
    SEMANTIC_OWNER_BINDINGS,
    build_single_baseline_graph,
)


def test_single_profile_has_one_physical_subgraph_and_six_semantic_owners() -> None:
    arguments = profile_build_arguments()
    semantic_owners = arguments.pop("semantic_owners")
    composition = build_single_baseline_graph(**arguments)

    assert tuple(composition.native_subgraphs()) == ("single_workflow",)
    assert len(set(SEMANTIC_OWNER_BINDINGS.values())) == 1
    assert set(SEMANTIC_OWNER_BINDINGS) == semantic_owners
