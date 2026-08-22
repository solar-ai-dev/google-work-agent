"""Thin LangGraph adapter for planning.choose_answer_or_action_from_route."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def choose_answer_or_action_from_route_node(
    state: Mapping[str, object],
    *,
    operation: Callable[[object], object],
) -> dict[str, object]:
    if "tool_route_plan" not in state:
        raise ValueError("tool_route_plan projection is required")
    return {"planning_disposition": operation(state["tool_route_plan"])}
