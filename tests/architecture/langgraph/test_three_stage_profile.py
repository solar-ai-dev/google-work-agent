"""THREE_STAGE composition contract."""

from tests.support.langgraph_profile import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.three_stage import (
    SEMANTIC_OWNER_BINDINGS,
    build_three_stage_graph,
)


def test_three_profile_has__three_physical_subgraphs__and_six_semantic_owners() -> None:
    bindings, controls, should_stop_for_cancel, checkpointer, semantic_owners = (
        profile_build_arguments()
    )
    composition = build_three_stage_graph(
        bindings=bindings,
        control_bindings=controls,
        should_stop_for_cancel=should_stop_for_cancel,
        checkpointer=checkpointer,
    )

    assert tuple(composition.native_subgraphs()) == ("stage_one", "stage_two", "stage_three")
    assert len(set(SEMANTIC_OWNER_BINDINGS.values())) == 3
    assert set(SEMANTIC_OWNER_BINDINGS) == semantic_owners
