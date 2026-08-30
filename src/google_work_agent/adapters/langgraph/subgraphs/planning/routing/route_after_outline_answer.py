"""Owner-local edge after planning.outline_answer."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_outline_answer(state: Mapping[str, object]) -> str:
    if not isinstance(state.get("answer_outline"), Mapping) and not isinstance(
        state.get("planning_confirmation"), Mapping
    ):
        raise ValueError("answer_outline is required before compose_answer")
    return "compose_answer"


__all__ = ["route_after_outline_answer"]
