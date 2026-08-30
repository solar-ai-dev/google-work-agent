"""Force rechecked findings through deterministic aggregation and validation."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_recheck_affected_dimensions(state: Mapping[str, object]) -> str:
    if state.get("__target__") == "end":
        return "end"
    if "affected_dimension_recheck" not in state:
        raise ValueError("affected-dimension recheck result is required")
    return "aggregate_findings"


__all__ = ["route_after_recheck_affected_dimensions"]
