from typing import TypedDict

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import (
    WorkAnalysisLocalState,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)


class ResolveTemporalDependenciesInput(TypedDict):
    work_facts: list[WorkFactV1]
    evidence: list[dict[str, object]]
    availability_results: list[dict[str, object]]
    allowed_evidence_refs: set[str]


def project_resolve_temporal_dependencies_input(
    state: WorkAnalysisLocalState,
) -> ResolveTemporalDependenciesInput:
    if "fact_candidates" not in state or "evidence" not in state or "evidence_refs" not in state:
        raise ValueError(
            "missing typed input projection for analysis.resolve_temporal_dependencies"
        )
    return {
        "work_facts": list(state["fact_candidates"]),
        "evidence": [dict(item) for item in state["evidence"]],
        "availability_results": list(state.get("availability_results", [])),
        "allowed_evidence_refs": set(state["evidence_refs"]),
    }
