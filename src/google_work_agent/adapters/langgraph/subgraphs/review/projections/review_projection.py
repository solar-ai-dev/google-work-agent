"""Allowlisted Review owner projection."""

from __future__ import annotations

from collections.abc import Mapping


_REVIEW_FIELDS = (
    "request_intent",
    "tool_route_plan",
    "retrieval_result",
    "work_analysis",
    "planning_result",
    "evidence",
    "policy_summary",
    "confirmation_response",
    "goal_evidence_findings",
    "action_scope_route_findings",
    "constraints_policy_findings",
    "aggregated_findings",
    "review_result",
    "affected_dimension_recheck",
)


def project_review_input(state: Mapping[str, object]) -> dict[str, object]:
    """Project only Review-owned inputs and local intermediate artifacts."""
    return {key: state[key] for key in _REVIEW_FIELDS if key in state}
