"""Allowlisted Review input projection."""

from __future__ import annotations

from collections.abc import Mapping


def project_review_input(state: Mapping[str, object]) -> dict[str, object]:
    allowed = (
        "request_intent",
        "tool_route_plan",
        "retrieval_result",
        "work_analysis",
        "planning_result",
        "evidence",
        "policy_summary",
        "confirmation_response",
    )
    return {key: state[key] for key in allowed if key in state}
