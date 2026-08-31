from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)


class ResolveEntityRelationsInput(TypedDict):
    work_facts: list[WorkFactV1]
    evidence: list[dict[str, object]]
    allowed_evidence_refs: set[str]


def project_resolve_entity_relations_input(
    state: WorkAnalysisLocalState,
) -> ResolveEntityRelationsInput:
    if "fact_candidates" not in state or "evidence" not in state or "evidence_refs" not in state:
        raise ValueError("missing typed input projection for analysis.resolve_entity_relations")
    return {
        "work_facts": list(state["fact_candidates"]),
        "evidence": [dict(item) for item in state["evidence"]],
        "allowed_evidence_refs": set(state["evidence_refs"]),
    }
