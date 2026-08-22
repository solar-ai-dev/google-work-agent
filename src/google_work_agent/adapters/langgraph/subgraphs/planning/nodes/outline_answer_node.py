"""Thin LangGraph adapter for planning.outline_answer."""

from __future__ import annotations

from collections.abc import Callable, Mapping


def outline_answer_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    if "answer_outline_input" not in state:
        raise ValueError("answer_outline_input projection is required")
    return {"answer_outline": operation(state["answer_outline_input"])}
