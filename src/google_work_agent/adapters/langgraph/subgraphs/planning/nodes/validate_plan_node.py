"""Thin LangGraph adapter for planning.validate_plan."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def validate_plan_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "plan_draft" not in state:
        raise ValueError("plan_draft projection is required")
    return {"validated_plan": operation(state["plan_draft"])}
