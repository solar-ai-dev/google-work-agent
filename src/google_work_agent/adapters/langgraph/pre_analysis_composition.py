"""Construction-only composition for the request-to-retrieval graph entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.acquisition import AcquisitionSubgraph
from google_work_agent.adapters.langgraph.subgraphs.context_retrieval import (
    ContextRetrieverSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing import (
    build_tool_routing_subgraph,
)
from google_work_agent.application.workflows import (
    ApiDiscoveryAcquisitionAgent,
    ContextRetrievalAgent,
    RequestUnderstandingAgent,
)
from google_work_agent.domain import ConnectorToolCatalog


@dataclass(frozen=True, slots=True)
class PreAnalysisSubgraphs:
    request_understanding: Any
    tool_route: Any
    acquisition: Any
    context_retrieval: Any


def build_pre_analysis_subgraphs(
    *,
    request_agent: RequestUnderstandingAgent,
    acquisition_agent: ApiDiscoveryAcquisitionAgent,
    context_agent: ContextRetrievalAgent,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    graph_profile: GraphProfile,
    transition_run: Callable[[str, str], None],
    merge_decision: Callable[..., Any],
) -> PreAnalysisSubgraphs:
    """Create nodes only; workflow policy remains in their Application owners."""

    return PreAnalysisSubgraphs(
        request_understanding=RequestUnderstandingSubgraph(
            agent=request_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
        ).build(),
        tool_route=build_tool_routing_subgraph(
            tool_catalog=tool_catalog,
            id_factory=id_factory,
            merge_decision=merge_decision,
        ),
        acquisition=AcquisitionSubgraph(
            agent=acquisition_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
        ).build(),
        context_retrieval=ContextRetrieverSubgraph(
            agent=context_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            merge_decision=merge_decision,
        ).build(),
    )


__all__ = ["PreAnalysisSubgraphs", "build_pre_analysis_subgraphs"]
