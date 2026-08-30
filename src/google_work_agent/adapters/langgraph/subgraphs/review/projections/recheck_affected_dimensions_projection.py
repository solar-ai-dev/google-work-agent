"""Typed input projection for review.recheck."""

from __future__ import annotations

from collections.abc import Mapping

_FIELDS = (
    "affected_dimensions",
    "affected_action_ids",
    "affected_route_ids",
    "request_intent",
    "tool_route_plan",
    "planning_result",
    "work_analysis",
    "evidence",
    "policy_summary",
    "confirmation_response",
)


def project_recheck_affected_dimensions_input(
    state: Mapping[str, object],
) -> dict[str, object]:
    return {key: state[key] for key in _FIELDS if key in state}


__all__ = ["project_recheck_affected_dimensions_input"]
