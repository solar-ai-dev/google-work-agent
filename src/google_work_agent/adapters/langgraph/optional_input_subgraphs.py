"""SIX_ROLE optional-input boundary retained for canonical Work Analysis."""

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import (
    WorkAnalysisSubgraph,
)


class CanonicalOptionalWorkAnalysisSubgraph(WorkAnalysisSubgraph):
    """Work Analysis that accepts the Canonical no-Retrieval entry path."""


__all__ = ["CanonicalOptionalWorkAnalysisSubgraph"]
