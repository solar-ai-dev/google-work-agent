"""Allowlisted Planning owner-local input projection."""

from __future__ import annotations

from collections.abc import Mapping

_ALLOWED = (
    "user_request",
    "request_intent",
    "tool_route_plan",
    "retrieval_result",
    "work_analysis_result",
    "evidence",
    "confirmation_response",
    "plan_artifact_id",
    "plan_revision",
    "plan_based_on",
    "action_ids_by_route",
    "planning_disposition",
    "answer_outline",
    "answer_draft",
    "action_objectives",
    "argument_candidates",
    "action_seeds",
    "dependencies",
    "plan_draft",
    "validated_plan",
)


def project_planning_input(state: Mapping[str, object]) -> dict[str, object]:
    return {key: state[key] for key in _ALLOWED if key in state}
