"""Graph profile selection for the LangGraph workflow runtime."""

from __future__ import annotations

from enum import StrEnum


class GraphProfile(StrEnum):
    """Supported LangGraph topology profiles."""

    SINGLE_BASELINE = "SINGLE_BASELINE"
    THREE_STAGE = "THREE_STAGE"
    SIX_ROLE_BASELINE = "SIX_ROLE_BASELINE"


class PromptArtifactGapError(RuntimeError):
    """Raised when the requested graph profile requires missing prompt artifacts."""


def supported_graph_profiles() -> tuple[GraphProfile, ...]:
    """Return the supported graph profile enum values in stable order."""

    return (
        GraphProfile.SINGLE_BASELINE,
        GraphProfile.THREE_STAGE,
        GraphProfile.SIX_ROLE_BASELINE,
    )
