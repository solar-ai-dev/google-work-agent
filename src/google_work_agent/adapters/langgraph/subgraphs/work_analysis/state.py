"""Canonical owner-local state for Work Analysis."""

from __future__ import annotations

from typing import TypedDict

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    CurrentSourceRelationV1,
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceDraftV1,
    RequestIntentV2,
)


class WorkAnalysisStateV2(TypedDict, total=False):
    """The exact #115-owned semantic channels; parent/runtime envelope stays external."""

    user_request: str
    request_intent: RequestIntentV2
    evidence: list[EvidenceDraftV1]
    evidence_refs: list[str]
    availability_results: list[dict[str, object]]
    confirmation_response: dict[str, object]
    current_source_relations: list[CurrentSourceRelationV1]
    fact_candidates: list[WorkFactV1]
    entity_relation_candidates: list[WorkRelationCandidateV1]
    temporal_dependency_candidates: list[WorkRelationCandidateV1]
    duplicate_conflict_candidates: list[WorkRelationCandidateV1]
    validated_relations: list[WorkRelationV1]
    relation_validation_ambiguities: list[WorkAmbiguityV1]


WorkAnalysisState = WorkAnalysisStateV2

__all__ = ["WorkAnalysisState", "WorkAnalysisStateV2"]
