"""Route Review invocation to initial inspection or post-Planning recheck."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_entry(state: Mapping[str, object]) -> str:
    phase = state.get("review_phase", "INITIAL")
    if phase == "INITIAL":
        return "inspect_goal_and_evidence"
    if phase == "RECHECK":
        return "recheck_affected_dimensions"
    raise ValueError("unknown Review phase")
