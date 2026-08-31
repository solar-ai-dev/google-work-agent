"""Minimum bounded-policy projection for review.inspect_constraints_policy."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict


class InspectConstraintsAndPolicySummaryInputV1(TypedDict):
    request_intent: dict[str, object]
    planning_result: dict[str, object]
    policy_summary: dict[str, object]
    work_analysis: NotRequired[dict[str, object]]
    evidence: NotRequired[list[dict[str, object]]]
    confirmation_response: NotRequired[dict[str, object]]


def project_inspect_constraints_and_policy_summary_input(
    state: Mapping[str, object],
) -> InspectConstraintsAndPolicySummaryInputV1:
    request_intent = _mapping(state, "request_intent")
    planning_result = _mapping(state, "planning_result")
    policy_summary = _mapping(state, "policy_summary")
    result: InspectConstraintsAndPolicySummaryInputV1 = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "policy_summary": dict(policy_summary),
    }
    work_analysis = state.get("work_analysis")
    if work_analysis is not None:
        if not isinstance(work_analysis, Mapping):
            raise ValueError("work_analysis must be an object")
        result["work_analysis"] = dict(work_analysis)
    evidence = state.get("evidence")
    if evidence is not None:
        if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
            raise ValueError("evidence must be a sequence")
        if not all(isinstance(item, Mapping) for item in evidence):
            raise ValueError("evidence items must be objects")
        result["evidence"] = [dict(item) for item in evidence]
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


__all__ = [
    "InspectConstraintsAndPolicySummaryInputV1",
    "project_inspect_constraints_and_policy_summary_input",
]
