"""Single production registry for the three Canonical graph profiles."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import Any, cast

from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    CompiledAgentSubgraphIdV1,
    SemanticAgentOwnerIdV1,
)


class GraphProfile(StrEnum):
    """Closed GraphProfileIdV1 vocabulary used by the runtime."""

    SINGLE_BASELINE = "SINGLE_BASELINE"
    THREE_STAGE = "THREE_STAGE"
    SIX_ROLE_BASELINE = "SIX_ROLE_BASELINE"


class PromptArtifactGapError(RuntimeError):
    """Raised when the selected profile requires an inactive Prompt artifact."""


type GraphProfileBuilder = Callable[..., Any]


def supported_graph_profiles() -> tuple[GraphProfile, ...]:
    """Return the exact closed profile set in stable order."""

    return (
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
        GraphProfile.SIX_ROLE_BASELINE,
    )


def get_graph_profile_builder(profile: GraphProfile | GraphProfileIdV1) -> GraphProfileBuilder:
    """Resolve the sole builder for a registered profile, without fallback."""

    from google_work_agent.adapters.langgraph.profiles.single_baseline import (
        build_single_baseline_graph,
    )
    from google_work_agent.adapters.langgraph.profiles.six_role_baseline import (
        build_six_role_baseline_graph,
    )
    from google_work_agent.adapters.langgraph.profiles.three_stage import (
        build_three_stage_graph,
    )

    builders: dict[GraphProfile, GraphProfileBuilder] = {
        GraphProfile.SINGLE_BASELINE: build_single_baseline_graph,
        GraphProfile.THREE_STAGE: build_three_stage_graph,
        GraphProfile.SIX_ROLE_BASELINE: build_six_role_baseline_graph,
    }
    try:
        normalized = GraphProfile(profile)
    except ValueError as error:
        raise ValueError(f"unknown graph profile: {profile}") from error
    return builders[normalized]


def get_profile_owner_bindings(
    profile: GraphProfile | GraphProfileIdV1,
) -> Mapping[SemanticAgentOwnerIdV1, CompiledAgentSubgraphIdV1]:
    """Return the exact semantic-owner to physical-subgraph binding."""

    from google_work_agent.adapters.langgraph.profiles.single_baseline import (
        SEMANTIC_OWNER_BINDINGS as single_bindings,
    )
    from google_work_agent.adapters.langgraph.profiles.six_role_baseline import (
        SEMANTIC_OWNER_BINDINGS as six_bindings,
    )
    from google_work_agent.adapters.langgraph.profiles.three_stage import (
        SEMANTIC_OWNER_BINDINGS as three_bindings,
    )

    bindings = {
        GraphProfile.SINGLE_BASELINE: single_bindings,
        GraphProfile.THREE_STAGE: three_bindings,
        GraphProfile.SIX_ROLE_BASELINE: six_bindings,
    }
    try:
        normalized = GraphProfile(profile)
    except ValueError as error:
        raise ValueError(f"unknown graph profile: {profile}") from error
    return MappingProxyType(
        cast(
            dict[SemanticAgentOwnerIdV1, CompiledAgentSubgraphIdV1],
            bindings[normalized],
        )
    )
