from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
)


class AssessInformationGapsInput(TypedDict):
    request_intent: RequestIntentV2
    work_facts: list[WorkFactV1]
    evidence: list[dict[str, object]]
    allowed_evidence_refs: set[str]
    confirmation_response: dict[str, object] | None


def project_assess_information_gaps_input(
    state: Mapping[str, object],
) -> AssessInformationGapsInput:
    required = ("request_intent", "fact_candidates", "evidence", "evidence_refs")
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.assess_information_gaps")
    response = state.get("confirmation_response")
    return {
        "request_intent": cast(RequestIntentV2, state["request_intent"]),
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "evidence": [dict(item) for item in cast(list[dict[str, object]], state["evidence"])],
        "allowed_evidence_refs": set(cast(list[str], state["evidence_refs"])),
        "confirmation_response": dict(response) if isinstance(response, Mapping) else None,
    }


__all__ = ["AssessInformationGapsInput", "project_assess_information_gaps_input"]
