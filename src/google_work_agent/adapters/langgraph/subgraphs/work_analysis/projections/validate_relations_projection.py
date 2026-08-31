from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    CurrentSourceRelationV1,
    WorkRelationCandidateV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)


class ValidateRelationsInput(TypedDict):
    work_facts: list[WorkFactV1]
    entity_relation_candidates: list[WorkRelationCandidateV1]
    temporal_dependency_candidates: list[WorkRelationCandidateV1]
    duplicate_conflict_candidates: list[WorkRelationCandidateV1]
    current_source_relations: list[CurrentSourceRelationV1]
    allowed_evidence_refs: set[str]


def project_validate_relations_input(state: WorkAnalysisLocalState) -> ValidateRelationsInput:
    required = (
        "fact_candidates",
        "entity_relation_candidates",
        "temporal_dependency_candidates",
        "duplicate_conflict_candidates",
        "evidence_refs",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.validate_relations")
    return {
        "work_facts": list(state["fact_candidates"]),
        "entity_relation_candidates": list(state["entity_relation_candidates"]),
        "temporal_dependency_candidates": list(state["temporal_dependency_candidates"]),
        "duplicate_conflict_candidates": list(state["duplicate_conflict_candidates"]),
        "current_source_relations": list(state.get("current_source_relations", [])),
        "allowed_evidence_refs": set(state["evidence_refs"]),
    }
