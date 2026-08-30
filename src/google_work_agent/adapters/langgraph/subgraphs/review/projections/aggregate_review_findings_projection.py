"""Typed input projection for review.aggregate_findings."""

from __future__ import annotations

from collections.abc import Mapping

_FIELDS = (
    "review_phase",
    "review_artifact_id",
    "review_revision",
    "review_based_on",
    "prior_review_findings",
    "affected_dimensions",
    "goal_evidence_result",
    "action_scope_route_result",
    "constraints_policy_result",
    "affected_dimension_recheck",
)


def project_aggregate_review_findings_input(
    state: Mapping[str, object],
) -> dict[str, object]:
    return {key: state[key] for key in _FIELDS if key in state}


__all__ = ["project_aggregate_review_findings_input"]
