"""Canonical owner-local state contract for Work Analysis."""

from __future__ import annotations

from typing import TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    RequestIntentV2,
    RetrievalNeedV1,
)


class WorkAnalysisStateV2(TypedDict, total=False):
    """The exact thirteen owner-local fields defined by Workflow 06."""

    user_request: str
    request_intent: RequestIntentV2
    evidence_refs: list[str]
    fact_candidates: list[WorkFactV1]
    entity_relation_candidates: list[WorkRelationCandidateV1]
    temporal_dependency_candidates: list[WorkRelationCandidateV1]
    duplicate_conflict_candidates: list[WorkRelationCandidateV1]
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]
    ambiguity_candidates: list[WorkAmbiguityV1]
    retrieval_needs: list[RetrievalNeedV1]
    operational_risk_candidates: list[WorkRiskV1]
    final_analysis: WorkAnalysisResultV2 | None


__all__ = ["WorkAnalysisStateV2"]
