"""Allowlisted Planning owner projection."""

from __future__ import annotations

from collections.abc import Mapping


_PLANNING_FIELDS = (
    "user_request",
    "request_intent",
    "tool_route_plan",
    "retrieval_result",
    "work_analysis",
    "evidence",
    "plan_review",
    "confirmation_response",
    "planning_disposition",
    "answer_outline",
    "answer_draft",
    "action_objectives",
    "argument_candidates",
    "dependencies",
    "plan_draft",
    "validated_plan",
)


def project_planning_input(state: Mapping[str, object]) -> dict[str, object]:
    """Project only Planning-owned inputs and local intermediate artifacts."""
    return {key: state[key] for key in _PLANNING_FIELDS if key in state}
