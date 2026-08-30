"""Deterministic applicability routing after ACTION scope inspection."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_inspect_action_scope_and_route(state: Mapping[str, object]) -> str:
    result = state.get("action_scope_route_result")
    if not isinstance(result, Mapping) or result.get("dimension") != (
        "review.inspect_action_scope_and_route"
    ):
        raise ValueError("action_scope_route_result is required before Review routing")
    if isinstance(state.get("policy_summary"), Mapping):
        return "inspect_constraints_policy"
    return "aggregate_findings"


__all__ = ["route_after_inspect_action_scope_and_route"]
