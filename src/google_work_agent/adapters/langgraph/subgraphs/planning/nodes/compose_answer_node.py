"""Thin LangGraph adapter for planning.compose_answer."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def compose_answer_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "compose_answer_input" not in state:
        raise ValueError("compose_answer_input projection is required")
    return {"answer_draft": operation(state["compose_answer_input"])}
