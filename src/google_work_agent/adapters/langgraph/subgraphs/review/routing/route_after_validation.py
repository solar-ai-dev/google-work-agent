"""Route from validated Review disposition."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_validation(state: Mapping[str, object]) -> str:
    result = state.get("review_result")
    if not isinstance(result, Mapping):
        raise ValueError("review_result is required")
    status = result.get("status")
    routes = {
        "PASS": "end",
        "REVISE": "recheck_affected_dimensions",
        "RETRIEVE_MORE": "end",
        "ROUTE_RECONSIDERATION": "end",
        "CONFIRM": "end",
        "BLOCK": "end",
    }
    if status not in routes:
        raise ValueError("unknown Review disposition")
    return routes[status]
