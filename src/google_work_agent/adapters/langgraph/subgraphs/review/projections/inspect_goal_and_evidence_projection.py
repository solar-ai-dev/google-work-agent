"""Minimum current-Run projection for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def project_inspect_goal_and_evidence_input(
    state: Mapping[str, object],
) -> dict[str, object]:
    request_intent = _mapping(state, "request_intent")
    planning_result = _mapping(state, "planning_result")
    evidence = _evidence(state.get("evidence", ()))
    result: dict[str, object] = {
        "request_intent": dict(request_intent),
        "planning_result": dict(planning_result),
        "evidence": evidence,
    }
    _copy_optional_mapping(state, result, "work_analysis")
    _copy_optional_mapping(state, result, "confirmation_response")
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


def _copy_optional_mapping(
    state: Mapping[str, object], result: dict[str, object], key: str
) -> None:
    value = state.get(key)
    if value is None:
        return
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} must be an object")
    result[key] = dict(value)


__all__ = ["project_inspect_goal_and_evidence_input"]
