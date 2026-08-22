"""Allowlisted Planning input projections."""

from __future__ import annotations

from collections.abc import Mapping


def project_planning_input(state: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "user_request",
        "request_intent",
        "tool_route_plan",
        "retrieval_result",
        "work_analysis",
        "evidence",
        "plan_review",
        "confirmation_response",
    )
    return {key: state[key] for key in allowed if key in state}
