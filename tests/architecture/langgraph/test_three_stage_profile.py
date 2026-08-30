"""THREE_STAGE composition contract."""

from tests.architecture.langgraph.profile_test_support import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.three_stage import (
    SEMANTIC_OWNER_BINDINGS,
    build_three_stage_graph,
)


def test_three_profile_has_three_physical_subgraphs_and_six_semantic_owners() -> None:
    arguments = profile_build_arguments()
    semantic_owners = arguments.pop("semantic_owners")
    composition = build_three_stage_graph(**arguments)

    assert tuple(composition.native_subgraphs()) == ("stage_one", "stage_two", "stage_three")
    assert len(set(SEMANTIC_OWNER_BINDINGS.values())) == 3
    assert set(SEMANTIC_OWNER_BINDINGS) == semantic_owners
