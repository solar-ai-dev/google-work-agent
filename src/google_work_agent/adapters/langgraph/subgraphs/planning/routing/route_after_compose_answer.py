"""Owner-local terminal edge after planning.compose_answer."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_compose_answer(state: Mapping[str, object]) -> str:
    if state.get("__planning_retry_outline__") is True:
        return "outline_answer"
    if not isinstance(state.get("final_result", state.get("answer_draft")), Mapping):
        raise ValueError("validated answer result is required")
    return "end"


__all__ = ["route_after_compose_answer"]
