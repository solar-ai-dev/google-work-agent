"""Deterministic applicability routing after goal/evidence inspection."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_inspect_goal_and_evidence(state: Mapping[str, object]) -> str:
    _require_result(state, "goal_evidence_result", "review.inspect_goal_and_evidence")
    planning_result = state.get("planning_result")
    if isinstance(planning_result, Mapping) and isinstance(planning_result.get("actions"), list):
        return "inspect_action_scope_route"
    if isinstance(state.get("policy_summary"), Mapping):
        return "inspect_constraints_policy"
    return "aggregate_findings"


def _require_result(state: Mapping[str, object], key: str, dimension: str) -> None:
    value = state.get(key)
    if not isinstance(value, Mapping) or value.get("dimension") != dimension:
        raise ValueError(f"{key} is required before Review routing")


__all__ = ["route_after_inspect_goal_and_evidence"]
