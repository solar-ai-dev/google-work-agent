from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
)


class DetectDuplicateConflictCandidatesInput(TypedDict):
    work_facts: list[WorkFactV1]
    entity_relations: list[WorkRelationV1]
    evidence: list[dict[str, object]]
    source_state: dict[str, object]
    allowed_evidence_refs: set[str]


def project_detect_duplicate_conflict_candidates_input(
    state: WorkAnalysisLocalState,
) -> DetectDuplicateConflictCandidatesInput:
    required = ("fact_candidates", "entity_relation_candidates", "evidence", "evidence_refs")
    if any(key not in state for key in required):
        raise ValueError(
            "missing typed input projection for analysis.detect_duplicate_conflict_candidates"
        )
    return {
        "work_facts": list(state["fact_candidates"]),
        "entity_relations": list(state["entity_relation_candidates"]),
        "evidence": [dict(item) for item in state["evidence"]],
        "source_state": {"availability_results": list(state.get("availability_results", []))},
        "allowed_evidence_refs": set(state["evidence_refs"]),
    }
