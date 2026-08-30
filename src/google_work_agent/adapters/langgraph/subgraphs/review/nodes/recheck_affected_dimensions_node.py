"""Thin adapter for review.recheck."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.recheck_affected_dimensions import (
    recheck_affected_dimensions,
)

from ..projections.recheck_affected_dimensions_projection import (
    project_recheck_affected_dimensions_input,
)

_DIMENSIONS: tuple[ReviewDimensionIdV1, ...] = (
    "review.inspect_goal_and_evidence",
    "review.inspect_action_scope_and_route",
    "review.inspect_constraints_and_policy_summary",
)


def recheck_affected_dimensions_node(
    state: Mapping[str, object], *, invoke: ReviewSemanticInvoker
) -> dict[str, object]:
    projected = project_recheck_affected_dimensions_input(state)
    result = recheck_affected_dimensions(
        affected_dimensions=_dimensions(projected.get("affected_dimensions")),
        affected_action_ids=_strings(
            projected.get("affected_action_ids", ()), "affected_action_ids"
        ),
        affected_route_ids=_strings(projected.get("affected_route_ids", ()), "affected_route_ids"),
        request_intent=_mapping(projected.get("request_intent"), "request_intent"),
        planning_result=_mapping(projected.get("planning_result"), "planning_result"),
        tool_route_plan=_optional_mapping(projected.get("tool_route_plan"), "tool_route_plan"),
        work_analysis=_optional_mapping(projected.get("work_analysis"), "work_analysis"),
        evidence=_mapping_sequence(projected.get("evidence", ()), "evidence"),
        policy_summary=_optional_mapping(projected.get("policy_summary"), "policy_summary"),
        confirmation_response=_optional_mapping(
            projected.get("confirmation_response"), "confirmation_response"
        ),
        invoke=invoke,
    )
    return {
        "affected_dimensions": result["affected_dimensions"],
        "affected_dimension_recheck": result["findings"],
    }


def _dimensions(value: object) -> tuple[ReviewDimensionIdV1, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError("affected_dimensions must be a sequence")
    requested = set(value)
    if not requested or requested - set(_DIMENSIONS):
        raise ValueError("invalid Review affected dimension")
    return tuple(dimension for dimension in _DIMENSIONS if dimension in requested)


def _strings(value: object, label: str) -> Sequence[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    if not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must contain strings")
    return cast(Sequence[str], value)


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} is required")
    return value


def _optional_mapping(value: object, label: str) -> Mapping[str, object] | None:
    if value is None:
        return None
    return _mapping(value, label)


def _mapping_sequence(value: object, label: str) -> Sequence[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be a sequence")
    if not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{label} must contain objects")
    return cast(Sequence[Mapping[str, object]], value)


__all__ = ["recheck_affected_dimensions_node"]
