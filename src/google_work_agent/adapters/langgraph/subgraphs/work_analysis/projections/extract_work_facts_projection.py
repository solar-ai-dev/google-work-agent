from typing import TypedDict, cast

from google_work_agent.adapters.langgraph.subgraphs.work_analysis.state import WorkAnalysisStateV2
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_candidates import (
    WorkAnalysisSemanticInputV1,
)


class ExtractWorkFactsInput(TypedDict):
    semantic_input: WorkAnalysisSemanticInputV1
    allowed_evidence_refs: set[str]


def project_extract_work_facts_input(state: WorkAnalysisStateV2) -> ExtractWorkFactsInput:
    required = ("user_request", "request_intent", "evidence", "evidence_refs")
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.extract_facts")
    semantic_input: WorkAnalysisSemanticInputV1 = {
        "user_request": state["user_request"],
        "request_intent": cast(dict[str, object], state["request_intent"]),
        "evidence": [dict(item) for item in state["evidence"]],
        "availability_results": list(state.get("availability_results", [])),
    }
    if "confirmation_response" in state:
        semantic_input["confirmation_response"] = dict(state["confirmation_response"])
    return {"semantic_input": semantic_input, "allowed_evidence_refs": set(state["evidence_refs"])}
