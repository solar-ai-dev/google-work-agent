"""Thin LangGraph adapter for review.inspect_goal_and_evidence."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def inspect_goal_and_evidence_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "inspect_goal_and_evidence_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"inspect_goal_and_evidence_result": operation(state[projection_key])}
