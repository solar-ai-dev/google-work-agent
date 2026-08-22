"""Thin LangGraph adapter for review.inspect_constraints_and_policy_summary."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def inspect_constraints_and_policy_summary_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "inspect_constraints_and_policy_summary_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"inspect_constraints_and_policy_summary_result": operation(state[projection_key])}
