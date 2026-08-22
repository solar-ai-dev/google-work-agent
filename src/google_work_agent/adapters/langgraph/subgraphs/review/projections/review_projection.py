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
    "review_phase",
    "review_artifact_id",
    "review_revision",
    "review_based_on",
    "prior_review_findings",
    "affected_action_ids",
    "affected_route_ids",
    "goal_evidence_findings",
    "action_scope_route_findings",
    "constraints_policy_findings",
    "affected_dimension_recheck",
    "aggregated_findings",
    "review_result",
)


def project_review_input(state: Mapping[str, object]) -> dict[str, object]:
    return {key: state[key] for key in _REVIEW_FIELDS if key in state}
