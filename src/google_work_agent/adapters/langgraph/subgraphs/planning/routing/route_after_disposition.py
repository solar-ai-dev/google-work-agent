"""Route after deterministic Planning disposition."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_disposition(state: Mapping[str, object]) -> str:
    value = state.get("planning_disposition")
    if value == "ANSWER":
        return "outline_answer"
    if value == "ACTION":
        return "draft_action_objective_per_output_route"
    raise ValueError("unknown planning_disposition")
