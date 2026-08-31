"""Minimum ACTION projection for review.inspect_action_scope_route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import NotRequired, TypedDict


class InspectActionScopeAndRouteInputV1(TypedDict):
    request_intent: dict[str, object]
    tool_route_plan: dict[str, object]
    planning_result: dict[str, object]
    evidence: list[dict[str, object]]
    work_analysis: NotRequired[dict[str, object]]
    confirmation_response: NotRequired[dict[str, object]]


def project_inspect_action_scope_and_route_input(
    state: Mapping[str, object],
) -> InspectActionScopeAndRouteInputV1:
    request_intent = _mapping(state, "request_intent")
    tool_route_plan = _mapping(state, "tool_route_plan")
    planning_result = _mapping(state, "planning_result")
    actions = planning_result.get("actions")
    if not isinstance(actions, list):
        raise ValueError("action-scope inspection requires an ACTION Planning artifact")
    evidence = state.get("evidence", ())
    if not isinstance(evidence, Sequence) or isinstance(evidence, str | bytes):
        raise ValueError("evidence must be a sequence")
    if not all(isinstance(item, Mapping) for item in evidence):
        raise ValueError("evidence items must be objects")
    result: InspectActionScopeAndRouteInputV1 = {
        "request_intent": dict(request_intent),
        "tool_route_plan": dict(tool_route_plan),
        "planning_result": dict(planning_result),
        "evidence": [dict(item) for item in evidence],
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


__all__ = [
    "InspectActionScopeAndRouteInputV1",
    "project_inspect_action_scope_and_route_input",
]
