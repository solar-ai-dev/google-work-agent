"""Minimum current-Run projection for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict


class InspectGoalAndEvidenceInputV1(TypedDict):
    request_intent: dict[str, object]
    planning_result: dict[str, object]
    evidence: list[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]


def project_inspect_goal_and_evidence_input(
    state: Mapping[str, object],
) -> InspectGoalAndEvidenceInputV1:
    request_intent = _mapping(state, "request_intent")
    planning_result = _mapping(state, "planning_result")
    evidence = _evidence(state.get("evidence", ()))
    result: InspectGoalAndEvidenceInputV1 = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "evidence": evidence,
    }
    work_analysis = state.get("work_analysis")
    if work_analysis is not None:
        if not isinstance(work_analysis, Mapping):
            raise ValueError("work_analysis must be an object")
        result["work_analysis"] = dict(work_analysis)
    confirmation = state.get("confirmation_response")
    if confirmation is not None:
        if not isinstance(confirmation, Mapping):
            raise ValueError("confirmation_response must be an object")
        result["confirmation_response"] = dict(confirmation)
    return result


def _mapping(state: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = state.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is required")
    return value


def _evidence(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        raise ValueError("evidence must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError("evidence items must be objects")
    return [dict(item) for item in value]


__all__ = ["InspectGoalAndEvidenceInputV1", "project_inspect_goal_and_evidence_input"]
