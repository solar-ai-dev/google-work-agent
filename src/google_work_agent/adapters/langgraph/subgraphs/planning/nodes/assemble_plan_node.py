"""Thin LangGraph adapter for planning.assemble_plan."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def assemble_plan_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "assemble_plan_input" not in state:
        raise ValueError("assemble_plan_input projection is required")
    return {"plan_draft": operation(state["assemble_plan_input"])}
