"""Construction-only composition for the request-to-retrieval graph entry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from google_work_agent.adapters.langgraph.profiles import GraphProfile
from google_work_agent.adapters.langgraph.subgraphs.acquisition import AcquisitionSubgraph
from google_work_agent.adapters.langgraph.subgraphs.projected_context_retrieval import (
    ProjectedContextRetrieverSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.request_understanding.graph import (
    RequestUnderstandingSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.tool_routing.graph import (
    build_tool_routing_subgraph,
)
from google_work_agent.application.orchestration.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
)
from google_work_agent.application.orchestration.contracts import (
    ConfirmationResponseV1,
    PolicyConfirmationReceiptV1,
)
from google_work_agent.application.orchestration.context_retrieval import (
    ContextRetrievalAgent,
)
from google_work_agent.application.orchestration.request_understanding import (
    RequestUnderstandingAgent,
)
from google_work_agent.application.orchestration.tool_route_semantic import ToolRouteAgent
from google_work_agent.application.orchestration.retrieval_data_boundary import (
    CheckpointSafeAcquisitionFacade,
)
from google_work_agent.application.orchestration.retrieval_evidence_store import RunScopedEvidenceStore
from google_work_agent.application.orchestration.retrieval_query_planner import (
    RetrievalQueryPlannerAgent,
)
from google_work_agent.application.orchestration.retrieval_read_cache import RunScopedReadResultCache
from google_work_agent.application.orchestration.retrieval_read_executor import RetrievalReadExecutor
from google_work_agent.application.orchestration.source_fetch_plan_builder import SourceFetchPlanBuilder
from google_work_agent.domain import ConnectorToolCatalog


@dataclass(frozen=True, slots=True)
class PreAnalysisSubgraphs:
    request_understanding: Any
    tool_route: Any
    # Compatibility-only direct acquisition graph.  No SINGLE/THREE/SIX
    # production topology routes to this field; it remains only for older
    # direct callers and is not accepted as a production privacy proof.
    acquisition: Any
    context_retrieval: Any


def build_pre_analysis_subgraphs(
    *,
    request_agent: RequestUnderstandingAgent,
    tool_route_agent: ToolRouteAgent,
    acquisition_agent: ApiDiscoveryAcquisitionAgent,
    retrieval_query_planner: RetrievalQueryPlannerAgent,
    context_agent: ContextRetrievalAgent,
    tool_catalog: ConnectorToolCatalog,
    id_factory: Callable[[], str],
    graph_profile: GraphProfile,
    transition_run: Callable[[str, str], None],
    merge_decision: Callable[..., Any],
    confirm_request_understanding_inline: Callable[
        [Any], tuple[ConfirmationResponseV1 | None, dict[str, object] | None]
    ],
    confirm_tool_route_inline: Callable[
        [Any], tuple[ConfirmationResponseV1 | None, dict[str, object] | None]
    ],
    confirm_context_retrieval_inline: Callable[
        [Any], tuple[ConfirmationResponseV1 | None, dict[str, object] | None]
    ],
    record_policy_confirmation_receipt: Callable[[str, PolicyConfirmationReceiptV1], None],
    evidence_store: RunScopedEvidenceStore,
    read_result_cache: RunScopedReadResultCache,
    retrieval_read_executor: RetrievalReadExecutor,
    default_tasklist_id_provider: Callable[[], str | None] | None = None,
) -> PreAnalysisSubgraphs:
    """Create nodes only; workflow policy remains in their Application owners."""

    checkpoint_safe_acquisition = CheckpointSafeAcquisitionFacade(
        agent=acquisition_agent,
        read_result_cache=read_result_cache,
    )
    return PreAnalysisSubgraphs(
        request_understanding=RequestUnderstandingSubgraph(
            agent=request_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
            confirm_inline=confirm_request_understanding_inline,
        ).build(),
        tool_route=build_tool_routing_subgraph(
            tool_catalog=tool_catalog,
            id_factory=id_factory,
            merge_decision=merge_decision,
            semantic_agent=tool_route_agent,
            confirm_inline=confirm_tool_route_inline,
            record_policy_confirmation_receipt=record_policy_confirmation_receipt,
        ),
        # Legacy standalone acquisition is intentionally left as an isolated
        # compatibility object: no production profile topology routes here.
        # Production Retrieval owns the checkpoint-safe facade below.
        acquisition=AcquisitionSubgraph(
            agent=acquisition_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
            read_result_cache=read_result_cache,
        ).build(),
        context_retrieval=ProjectedContextRetrieverSubgraph(
            agent=context_agent,
            id_factory=id_factory,
            graph_profile=graph_profile,
            transition_run=transition_run,
            merge_decision=merge_decision,
            evidence_store=evidence_store,
            acquisition_agent=checkpoint_safe_acquisition,
            retrieval_query_planner=retrieval_query_planner,
            source_fetch_plan_builder=SourceFetchPlanBuilder(),
            read_result_cache=read_result_cache,
            retrieval_read_executor=retrieval_read_executor,
            confirm_inline=confirm_context_retrieval_inline,
            default_tasklist_id_provider=default_tasklist_id_provider,
        ).build(),
    )


__all__ = ["PreAnalysisSubgraphs", "build_pre_analysis_subgraphs"]
