"""Canonical owner-local state for the Retrieval subgraph."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentLocalStateV1,
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    RetrievalQueryPlanV2,
)
from google_work_agent.application.agents.retrieval.contracts.query_plan import (
    SourceFetchPlanV1 as V2SourceFetchPlanV1,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
    ContextBundleV1,
    EvidenceDraftV1,
    EvidenceSelectionResultV2,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SourceFetchPlanV1,
    SufficiencyResultV2,
)
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.agents.retrieval.resolve_availability import AvailableIntervalV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
    ScopeExpansionRequiredV1,
    ToolRoutePlanV2,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
)


class ContextRetrievalInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Retrieval."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: (
        ScopeExpansionRequiredV1 | RouteReconsiderationRequiredV1 | RetrievalRequiredV1 | None
    )
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    exclusion_obligation_segment_ids: list[str]
    pending_user_retrieval_need: RetrievalNeedV1 | None


class ContextRetrievalLocalState(GraphState):
    """Retrieval-owned runtime channels used by its graph and nodes."""

    input_route_ref: NotRequired[StateArtifactRefV1]
    input_routes: NotRequired[list[InputToolRouteV1]]
    query_attempts: NotRequired[list[QueryAttemptV1]]
    source_statuses: NotRequired[list[RetrievalSourceStatusV1]]
    read_result_handles: NotRequired[list[str]]
    segment_handles: NotRequired[list[str]]
    rag_candidates: NotRequired[list[RagCandidateV1]]
    evidence_selection: NotRequired[EvidenceSelectionResultV2 | None]
    sufficiency: NotRequired[SufficiencyResultV2 | None]
    final_result: NotRequired[RetrievalResultV1 | None]
    context_bundle: NotRequired[ContextBundleV1]
    evidence_drafts: NotRequired[list[EvidenceDraftV1]]
    llm_provider_result: NotRequired[dict[str, object] | None]
    query_plan: NotRequired[RetrievalQueryPlanV2 | None]
    segments: NotRequired[list[str]]
    ranked_segments: NotRequired[list[RagCandidateV1]]
    availability_results: NotRequired[list[AvailableIntervalV1]]
    __context_agent_local__: NotRequired[AgentLocalStateV1]
    __context_rag_candidates__: NotRequired[list[RagCandidateV1]]
    __context_selection_output__: NotRequired[EvidenceSelectionResultV2]
    __context_sufficiency_output__: NotRequired[SufficiencyResultV2]
    __context_current_round_no__: NotRequired[int]
    __context_read_result_handles__: NotRequired[list[str]]
    __context_read_bindings__: NotRequired[dict[str, dict[str, str]]]
    __context_segment_handles__: NotRequired[list[str]]
    __context_query_attempts__: NotRequired[list[QueryAttemptV1]]
    __context_followup_planner_input__: NotRequired[dict[str, object]]
    __context_canonical_plans__: NotRequired[dict[str, V2SourceFetchPlanV1]]
    __context_followup_operation__: NotRequired[str]
    __context_next_page_handles__: NotRequired[dict[str, str]]
    __context_detail_candidates__: NotRequired[dict[str, str]]
    __context_retrieval_retry_confirmation__: NotRequired[bool]


class RetrievalStateV2(TypedDict, total=False):
    """The exact 05-owned Retrieval-local semantic state."""

    request_intent: RequestIntentV2
    input_route_ref: StateArtifactRefV1
    input_routes: list[InputToolRouteV1]
    query_plan: RetrievalQueryPlanV2 | None
    query_attempts: list[QueryAttemptV1]
    source_statuses: list[RetrievalSourceStatusV1]
    read_result_handles: list[str]
    segment_handles: list[str]
    availability_results: list[AvailableIntervalV1]
    rag_candidates: list[RagCandidateV1]
    exclusion_obligation_segment_ids: list[str]
    pending_user_retrieval_need: RetrievalNeedV1 | None
    evidence_selection: EvidenceSelectionResultV2 | None
    sufficiency: SufficiencyResultV2 | None
    final_result: RetrievalResultV1 | None


RetrievalState = RetrievalStateV2

__all__ = [
    "ContextRetrievalInputState",
    "ContextRetrievalLocalState",
    "RetrievalState",
    "RetrievalStateV2",
]
