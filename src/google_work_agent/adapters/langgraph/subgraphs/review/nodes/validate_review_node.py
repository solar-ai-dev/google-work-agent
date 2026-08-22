"""Thin LangGraph adapter for review.validate_review."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def validate_review_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "validate_review_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"validate_review_result": operation(state[projection_key])}
