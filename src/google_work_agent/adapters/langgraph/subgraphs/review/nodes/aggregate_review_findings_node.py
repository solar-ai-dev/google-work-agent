"""Thin adapter for review.aggregate_review_findings."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import (
    project_review_input,
)
from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)


def aggregate_review_findings_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_review_input(state)
    phase = projected.get("review_phase", "INITIAL")
    if phase == "RECHECK":
        prior = list(_sequence(projected.get("prior_review_findings", ()), "prior_review_findings"))
        fresh = list(
            _sequence(projected.get("affected_dimension_recheck", ()), "affected_dimension_recheck")
        )
        fresh_dimensions = {
            item.get("dimension") for item in fresh if isinstance(item.get("dimension"), str)
        }
        findings = [item for item in prior if item.get("dimension") not in fresh_dimensions] + fresh
    elif phase == "INITIAL":
        findings = []
        for key in (
            "goal_evidence_findings",
            "action_scope_route_findings",
            "constraints_policy_findings",
        ):
            findings.extend(_sequence(projected.get(key, ()), key))
    else:
        raise ValueError("unknown Review phase")

    artifact_id = projected.get("review_artifact_id")
    revision = projected.get("review_revision")
    based_on = projected.get("review_based_on", ())
    if not isinstance(artifact_id, str) or not isinstance(revision, int):
        raise ValueError("review_artifact_id and review_revision are required")
    if not isinstance(based_on, Sequence) or isinstance(based_on, (str, bytes)):
        raise ValueError("review_based_on must be a sequence")
    result = aggregate_review_findings(
        findings,
        artifact_id=artifact_id,
        revision=revision,
        based_on=based_on,  # type: ignore[arg-type]
    )
    return {"aggregated_findings": result}


def _sequence(value: object, label: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    return value  # type: ignore[return-value]
