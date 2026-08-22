"""Thin adapter for review.recheck_affected_dimensions."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.review.projections.review_projection import (
    project_review_input,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimension,
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.recheck_affected_dimensions import (
    recheck_affected_dimensions,
)


def recheck_affected_dimensions_node(
    state: Mapping[str, object], *, invoke: ReviewSemanticInvoker
) -> dict[str, object]:
    projected = project_review_input(state)
    prior = _sequence(projected.get("prior_review_findings", ()), "prior_review_findings")
    dimensions = _dimension_sequence(projected.get("affected_dimensions", ()))
    action_ids = _string_sequence(projected.get("affected_action_ids", ()), "affected_action_ids")
    route_ids = _string_sequence(projected.get("affected_route_ids", ()), "affected_route_ids")
    fresh = recheck_affected_dimensions(
        prior,
        affected_dimensions=dimensions,
        affected_action_ids=action_ids,
        affected_route_ids=route_ids,
        request_intent=_mapping(projected, "request_intent"),
        tool_route_plan=_mapping(projected, "tool_route_plan"),
        planning_result=_mapping(projected, "planning_result"),
        work_analysis=_optional_mapping(projected.get("work_analysis")),
        evidence=_sequence(projected.get("evidence", ()), "evidence"),
        policy_summary=_optional_mapping(projected.get("policy_summary")),
        invoke=invoke,
    )
    return {"affected_dimension_recheck": fresh}


def _mapping(projected: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = projected.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"{key} is required")
    return value


def _optional_mapping(value: object) -> Mapping[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ValueError("optional Review input must be an object")
    return value


def _sequence(value: object, label: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    return value  # type: ignore[return-value]


def _string_sequence(value: object, label: str) -> Sequence[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    if not all(isinstance(item, str) for item in value):
        raise ValueError(f"{label} must contain strings")
    return value  # type: ignore[return-value]


def _dimension_sequence(value: object) -> Sequence[ReviewDimension]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("affected_dimensions must be a sequence")
    allowed = {"GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"}
    if not all(isinstance(item, str) and item in allowed for item in value):
        raise ValueError("affected_dimensions contains an invalid Review dimension")
    return value  # type: ignore[return-value]
