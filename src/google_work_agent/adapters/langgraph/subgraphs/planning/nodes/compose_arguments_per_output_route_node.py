"""Thin LangGraph adapter for planning.compose_arguments_per_output_route."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def compose_arguments_per_output_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "arguments_input" not in state:
        raise ValueError("arguments_input projection is required")
    return {"argument_candidates": operation(state["arguments_input"])}
