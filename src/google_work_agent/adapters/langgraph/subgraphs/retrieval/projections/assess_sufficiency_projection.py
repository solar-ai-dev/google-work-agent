from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    EvidenceSelectionResultV2,
)


class AssessSufficiencyInput(TypedDict):
    request_intent: RequestIntentV2
    evidence_selection: EvidenceSelectionResultV2


def project_assess_sufficiency_input(state: Mapping[str, object]) -> AssessSufficiencyInput:
    request_intent = state.get("request_intent")
    selection = state.get("evidence_selection")
    if not isinstance(request_intent, Mapping):
        raise ValueError("retrieval request_intent is required")
    if not isinstance(selection, Mapping):
        raise ValueError("retrieval evidence_selection is required")
    return {
        "request_intent": cast(RequestIntentV2, request_intent),
        "evidence_selection": cast(EvidenceSelectionResultV2, selection),
    }


__all__ = ["AssessSufficiencyInput", "project_assess_sufficiency_input"]
