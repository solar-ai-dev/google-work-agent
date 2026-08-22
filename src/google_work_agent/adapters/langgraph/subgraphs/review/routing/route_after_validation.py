"""Route from validated Review disposition without performing cross-owner work."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_validation(state: Mapping[str, object]) -> str:
    result = state.get("review_result")
    if not isinstance(result, Mapping):
        raise ValueError("review_result is required")
    status = result.get("status")
    if status not in {
        "PASS",
        "REVISE",
        "RETRIEVE_MORE",
        "ROUTE_RECONSIDERATION",
        "CONFIRM",
        "BLOCK",
    }:
        raise ValueError("unknown Review disposition")
    return "end"
