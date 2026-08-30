"""Minimum ACTION projection for review.inspect_action_scope_route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def project_inspect_action_scope_and_route_input(
    state: Mapping[str, object],
) -> dict[str, object]:
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
    result: dict[str, object] = {
        "request_intent": dict(request_intent),
        "tool_route_plan": dict(tool_route_plan),
        "planning_result": dict(planning_result),
        "evidence": [dict(item) for item in evidence],
    }
    _copy_optional_mapping(state, result, "work_analysis")
    _copy_optional_mapping(state, result, "confirmation_response")
    return result


def _mapping(state: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = state.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is required")
    return value


def _copy_optional_mapping(
    state: Mapping[str, object], result: dict[str, object], key: str
) -> None:
    value = state.get(key)
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    result[key] = dict(value)


__all__ = ["project_inspect_action_scope_and_route_input"]
