"""Thin adapter for review.aggregate_findings and its supporting validator."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
)
from google_work_agent.application.agents.review.validate_review import validate_review

from ..projections.aggregate_review_findings_projection import (
    project_aggregate_review_findings_input,
)

_DIMENSIONS: tuple[ReviewDimensionIdV1, ...] = (
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
)


def aggregate_review_findings_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_aggregate_review_findings_input(state)
    phase = projected.get("review_phase", "INITIAL")
    if phase == "INITIAL":
        findings = _initial_findings(projected)
    elif phase == "RECHECK":
        prior = list(_finding_sequence(projected.get("prior_review_findings", ())))
        fresh = list(_finding_sequence(projected.get("affected_dimension_recheck", ())))
        affected = set(_dimension_sequence(projected.get("affected_dimensions", ()), True))
        findings = [item for item in prior if item.get("dimension") not in affected] + fresh
    else:
        raise ValueError("unknown Review phase")

    artifact_id = projected.get("review_artifact_id")
    revision = projected.get("review_revision")
    based_on = projected.get("review_based_on", ())
    if not isinstance(artifact_id, str) or not artifact_id:
        raise ValueError("review_artifact_id is required")
    if not isinstance(revision, int) or isinstance(revision, bool):
        raise ValueError("review_revision is required")
    result = validate_review(
        aggregate_review_findings(
            findings,
            artifact_id=artifact_id,
            revision=revision,
            based_on=_mapping_sequence(based_on, "review_based_on"),
        )
    )
    return {
        "prior_review_findings": findings,
        "review_result": result,
        "plan_review": result,
        "workflow_signal": None,
    }


def _initial_findings(projected: Mapping[str, object]) -> list[Mapping[str, object]]:
    findings: list[Mapping[str, object]] = []
    for key in ("goal_evidence_result", "action_scope_route_result", "constraints_policy_result"):
        value = projected.get(key)
        if value is None:
            continue
        result = _mapping(value, key)
        findings.extend(_finding_sequence(result.get("findings", ())))
    return findings


def _finding_sequence(value: object) -> Sequence[Mapping[str, object]]:
    return _mapping_sequence(value, "Review findings")


def _mapping_sequence(value: object, label: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} must contain objects")
    return cast(Sequence[Mapping[str, object]], value)


def _dimension_sequence(value: object, nonempty: bool = False) -> tuple[ReviewDimensionIdV1, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("affected_dimensions must be a sequence")
    requested = set(value)
    if (nonempty and not requested) or requested - set(_DIMENSIONS):
        raise ValueError("affected_dimensions contains an invalid Review dimension")
    return tuple(dimension for dimension in _DIMENSIONS if dimension in requested)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


__all__ = ["aggregate_review_findings_node"]
