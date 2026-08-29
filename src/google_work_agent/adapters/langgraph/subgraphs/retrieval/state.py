"""Canonical owner-local state for the Retrieval subgraph."""

from __future__ import annotations

from typing import TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    StateArtifactRefV1,
)
from google_work_agent.application.agents.retrieval.contracts.query_attempt import QueryAttemptV1
from google_work_agent.application.agents.retrieval.rag_retrieve_rerank import RagCandidateV1
from google_work_agent.application.agents.retrieval.resolve_availability import AvailableIntervalV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceSelectionResultV2,
    RequestIntentV2,
    RetrievalNeedV1,
    RetrievalResultV1,
    RetrievalSourceStatusV1,
    SufficiencyResultV2,
)
from google_work_agent.application.orchestration.retrieval_v2_contracts import (
    RetrievalQueryPlanV2,
)


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

__all__ = ["RetrievalState", "RetrievalStateV2"]
