"""Thin LangGraph adapter for review.inspect_action_scope_and_route."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def inspect_action_scope_and_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projection_key = "inspect_action_scope_and_route_input"
    if projection_key not in state:
        raise ValueError(f"{projection_key} projection is required")
    return {"inspect_action_scope_and_route_result": operation(state[projection_key])}
