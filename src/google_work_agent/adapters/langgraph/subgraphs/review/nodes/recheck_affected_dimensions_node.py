"""Thin LangGraph adapter for review.recheck_affected_dimensions."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def recheck_affected_dimensions_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "recheck_affected_dimensions_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"recheck_affected_dimensions_result": operation(state[projection_key])}
