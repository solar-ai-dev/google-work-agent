"""Terminate one Review invocation after validated aggregation."""

from __future__ import annotations

from collections.abc import Mapping


def route_after_aggregate_review_findings(state: Mapping[str, object]) -> str:
    result = state.get("review_result")
    if not isinstance(result, Mapping) or result.get("status") not in {
        "PASS",
        "REVISE",
        "RETRIEVE_MORE",
        "ROUTE_RECONSIDERATION",
        "CONFIRM",
        "BLOCK",
    }:
        raise ValueError("validated review_result is required")
    return "end"


__all__ = ["route_after_aggregate_review_findings"]
