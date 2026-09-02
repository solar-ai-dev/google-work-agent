"""SINGLE_BASELINE composition contract."""

from tests.support.langgraph_profile import profile_build_arguments

from google_work_agent.adapters.langgraph.profiles.single_baseline import (
    SEMANTIC_OWNER_BINDINGS,
    build_single_baseline_graph,
)


def test_single_profile_has__one_physical_subgraph__and_six_semantic_owners() -> None:
    bindings, controls, should_stop_for_cancel, checkpointer, semantic_owners = (
        profile_build_arguments()
    )
    composition = build_single_baseline_graph(
        bindings=bindings,
        control_bindings=controls,
        should_stop_for_cancel=should_stop_for_cancel,
        checkpointer=checkpointer,
    )

    assert tuple(composition.native_subgraphs()) == ("single_workflow",)
    assert len(set(SEMANTIC_OWNER_BINDINGS.values())) == 1
    assert set(SEMANTIC_OWNER_BINDINGS) == semantic_owners
