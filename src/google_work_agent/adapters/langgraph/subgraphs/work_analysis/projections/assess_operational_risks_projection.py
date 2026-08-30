from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkFactV1,
    WorkRelationV1,
)
from google_work_agent.application.orchestration.handoff_contracts import RequestIntentV2


class AssessOperationalRisksInput(TypedDict):
    request_intent: RequestIntentV2
    work_facts: list[WorkFactV1]
    validated_relations: list[WorkRelationV1]
    evidence: list[dict[str, object]]
    allowed_evidence_refs: set[str]
    policy_summary: dict[str, object] | None
    confirmation_response: dict[str, object] | None


def project_assess_operational_risks_input(
    state: Mapping[str, object],
) -> AssessOperationalRisksInput:
    required = (
        "request_intent",
        "fact_candidates",
        "validated_relations",
        "evidence",
        "evidence_refs",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.assess_operational_risks")
    response = state.get("confirmation_response")
    summary = state.get("policy_summary")
    return {
        "request_intent": cast(RequestIntentV2, state["request_intent"]),
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "validated_relations": cast(list[WorkRelationV1], state["validated_relations"]),
        "evidence": [dict(item) for item in cast(list[dict[str, object]], state["evidence"])],
        "allowed_evidence_refs": set(cast(list[str], state["evidence_refs"])),
        "policy_summary": dict(summary) if isinstance(summary, Mapping) else None,
        "confirmation_response": dict(response) if isinstance(response, Mapping) else None,
    }


__all__ = ["AssessOperationalRisksInput", "project_assess_operational_risks_input"]
