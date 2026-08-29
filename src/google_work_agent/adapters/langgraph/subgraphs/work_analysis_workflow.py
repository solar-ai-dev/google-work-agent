"""Temporary non-semantic import path for the canonical Work Analysis graph.

The production capability authority lives in ``subgraphs.work_analysis``.
This module remains only until the #116 parent integration removes the old
module path; it owns no Work Analysis behavior.
"""

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.graph import WorkAnalysisSubgraph

__all__ = ["WorkAnalysisSubgraph"]
