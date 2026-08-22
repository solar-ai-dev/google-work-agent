"""Thin LangGraph adapter for planning.draft_action_objective_per_output_route."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def draft_action_objective_per_output_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "action_objective_input" not in state:
        raise ValueError("action_objective_input projection is required")
    return {"action_objectives": operation(state["action_objective_input"])}
