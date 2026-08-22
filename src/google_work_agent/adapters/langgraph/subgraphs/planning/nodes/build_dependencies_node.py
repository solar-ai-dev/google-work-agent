"""Thin LangGraph adapter for planning.build_dependencies."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def build_dependencies_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "action_seeds" not in state:
        raise ValueError("action_seeds projection is required")
    return {"dependencies": operation(state["action_seeds"])}
