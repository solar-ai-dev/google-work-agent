from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.retrieval.resolve_availability import AvailableIntervalV1
from google_work_agent.application.orchestration.handoff_contracts import (
    EvidenceSelectionResultV2,
    RequestIntentV2,
    SufficiencyResultV2,
)


class FinalizeRetrievalInput(TypedDict):
    request_intent: RequestIntentV2
    selection_result: EvidenceSelectionResultV2
    sufficiency_result: SufficiencyResultV2
    availability_results: list[AvailableIntervalV1]
    exclusion_obligation_segment_ids: list[str]


def project_finalize_retrieval_input(state: Mapping[str, object]) -> FinalizeRetrievalInput:
    request_intent = state.get("request_intent")
    selection = state.get("evidence_selection")
    sufficiency = state.get("sufficiency")
    availability = state.get("availability_results", [])
    exclusions = state.get("exclusion_obligation_segment_ids", [])
    if not isinstance(request_intent, Mapping):
        raise ValueError("retrieval request_intent is required")
    if not isinstance(selection, Mapping):
        raise ValueError("retrieval evidence_selection is required")
    if not isinstance(sufficiency, Mapping):
        raise ValueError("retrieval sufficiency is required")
    if not isinstance(availability, list):
        raise ValueError("retrieval availability_results must be a list")
    if not isinstance(exclusions, list) or not all(isinstance(item, str) for item in exclusions):
        raise ValueError("retrieval exclusion obligations must be list[str]")
    return {
        "request_intent": cast(RequestIntentV2, request_intent),
        "selection_result": cast(EvidenceSelectionResultV2, selection),
        "sufficiency_result": cast(SufficiencyResultV2, sufficiency),
        "availability_results": cast(list[AvailableIntervalV1], availability),
        "exclusion_obligation_segment_ids": list(exclusions),
    }


__all__ = ["FinalizeRetrievalInput", "project_finalize_retrieval_input"]
