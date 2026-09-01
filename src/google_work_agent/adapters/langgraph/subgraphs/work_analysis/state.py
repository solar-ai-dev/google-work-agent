"""Canonical owner-local state contract for Work Analysis."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.subgraph_state import (
    AgentLocalStateV1,
    AgentSubgraphInputEnvelope,
)
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceDraftV1,
    RetrievalResultV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    CurrentSourceRelationV1,
    InformationGapAssessmentV1,
    OperationalRiskAssessmentV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
)


class WorkAnalysisInputState(AgentSubgraphInputEnvelope, total=False):
    """Parent projection owned by Work Analysis."""

    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    retrieval_result: RetrievalResultV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


class WorkAnalysisLocalState(GraphState):
    """Work Analysis-owned runtime channels used by its graph and nodes."""

    user_request: NotRequired[str]
    evidence: NotRequired[list[EvidenceDraftV1]]
    evidence_refs: NotRequired[list[str]]
    availability_results: NotRequired[list[dict[str, object]]]
    confirmation_response: NotRequired[dict[str, object]]
    current_source_relations: NotRequired[list[CurrentSourceRelationV1]]
    fact_candidates: NotRequired[list[WorkFactV1]]
    entity_relation_candidates: NotRequired[list[WorkRelationV1]]
    temporal_dependency_candidates: NotRequired[list[WorkRelationV1]]
    duplicate_conflict_candidates: NotRequired[list[WorkRelationV1]]
    validated_relations: NotRequired[list[WorkRelationV1]]
    relation_validation_ambiguities: NotRequired[list[WorkAmbiguityV1]]
    ambiguity_candidates: NotRequired[list[WorkAmbiguityV1]]
    retrieval_needs: NotRequired[list[RetrievalNeedV1]]
    operational_risk_candidates: NotRequired[list[WorkRiskV1]]
    final_analysis: NotRequired[WorkAnalysisResultV2 | None]
    __analysis_information_gap_assessment__: NotRequired[InformationGapAssessmentV1]
    __analysis_operational_risk_assessment__: NotRequired[OperationalRiskAssessmentV1]
    __analysis_noncomplete_disposition__: NotRequired[str]
    __analysis_agent_local__: NotRequired[AgentLocalStateV1]
    __work_analysis_retry_confirmation__: NotRequired[bool]


class WorkAnalysisStateV2(TypedDict, total=False):
    """The exact thirteen owner-local fields defined by Workflow 06."""

    user_request: str
    request_intent: RequestIntentV2
    evidence_refs: list[str]
    fact_candidates: list[WorkFactV1]
    entity_relation_candidates: list[WorkRelationV1]
    temporal_dependency_candidates: list[WorkRelationV1]
    duplicate_conflict_candidates: list[WorkRelationV1]
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]
    ambiguity_candidates: list[WorkAmbiguityV1]
    retrieval_needs: list[RetrievalNeedV1]
    operational_risk_candidates: list[WorkRiskV1]
    final_analysis: WorkAnalysisResultV2 | None


__all__ = [
    "WorkAnalysisInputState",
    "WorkAnalysisLocalState",
    "WorkAnalysisStateV2",
]
