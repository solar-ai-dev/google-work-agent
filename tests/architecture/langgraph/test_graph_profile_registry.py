"""Architecture closure for the single Graph Profile Registry."""

import pytest

from google_work_agent.adapters.langgraph.profiles.profile_registry import (
    GraphProfile,
    get_graph_profile_builder,
    get_profile_owner_bindings,
    supported_graph_profiles,
)


def test_registry_closes__the_exact_three__profile_builder_set() -> None:
    profiles = supported_graph_profiles()

    assert profiles == tuple(GraphProfile)
    assert [get_graph_profile_builder(item).__name__ for item in profiles] == [
        "build_single_baseline_graph",
        "build_three_stage_graph",
        "build_six_role_baseline_graph",
    ]


def test_registry_fails__closed_without__profile_fallback() -> None:
    with pytest.raises(ValueError, match="unknown graph profile"):
        get_graph_profile_builder("UNKNOWN")  # type: ignore[arg-type]


def test_every_profile__preserves_all__six_semantic_owners() -> None:
    expected = {
        "REQUEST_UNDERSTANDING",
        "TOOL_ROUTE",
        "RETRIEVAL",
        "WORK_ANALYSIS",
        "PLANNING",
        "REVIEW",
    }

    for profile in supported_graph_profiles():
        assert set(get_profile_owner_bindings(profile)) == expected
