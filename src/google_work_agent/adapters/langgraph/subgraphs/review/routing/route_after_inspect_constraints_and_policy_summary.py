"""Deterministic routing after bounded constraints/policy-summary inspection."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_inspect_constraints_and_policy_summary(state: Mapping[str, object]) -> str:
    result = state.get("constraints_policy_result")
    if not isinstance(result, Mapping) or result.get("dimension") != (
        "review.inspect_constraints_and_policy_summary"
    ):
        raise ValueError("constraints_policy_result is required before Review routing")
    return "aggregate_findings"


__all__ = ["route_after_inspect_constraints_and_policy_summary"]
