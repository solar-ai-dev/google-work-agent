"""Thin LangGraph adapter for review.aggregate_review_findings."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def aggregate_review_findings_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "aggregate_review_findings_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"aggregate_review_findings_result": operation(state[projection_key])}
