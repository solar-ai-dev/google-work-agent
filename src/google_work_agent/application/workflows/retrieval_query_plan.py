"""Retrieval-local semantic contract for initial and follow-up query planning."""

from __future__ import annotations

from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import SufficiencyIssueV2
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2

FollowupOperationKind = Literal["SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"]


class ConstraintDeltaV1(TypedDict):
    added_constraints: Required[list[str]]
    removed_constraints: Required[list[str]]


class RouteQueryIntentV1(TypedDict):
    """One semantic operation constrained to a frozen input route."""

    route_id: Required[str]
    operation_kind: Required[FollowupOperationKind]
    reason_codes: Required[list[str]]
    constraint_delta: Required[ConstraintDeltaV1 | None]
    detail_candidate_ref: Required[str | None]


class FollowupQueryPlanValidationError(ValueError):
    """A planner proposal cannot be executed in the current local loop."""


def validate_followup_route_query_intent(
    *,
    value: object,
    frozen_route: ToolRoutePlanV2,
    unresolved_issues: list[SufficiencyIssueV2],
    detail_candidate_refs: frozenset[str],
) -> RouteQueryIntentV1:
    """Validate semantic planner output without provider or cache side effects."""
    if not isinstance(value, dict) or set(value) != {
        "route_id",
        "operation_kind",
        "reason_codes",
        "constraint_delta",
        "detail_candidate_ref",
    }:
        raise FollowupQueryPlanValidationError("invalid follow-up query intent schema")
    route_id = value["route_id"]
    operation_kind = value["operation_kind"]
    reason_codes = value["reason_codes"]
    delta = value["constraint_delta"]
    detail_candidate_ref = value["detail_candidate_ref"]
    if not isinstance(route_id, str) or not any(
        route["route_id"] == route_id for route in frozen_route["input_plan"]["input_routes"]
    ):
        raise FollowupQueryPlanValidationError("ROUTE_RECONSIDERATION_REQUIRED")
    if operation_kind not in {"SEARCH", "NEXT_PAGE", "DETAIL_FETCH", "FREEBUSY"}:
        raise FollowupQueryPlanValidationError("invalid follow-up operation")
    if not isinstance(reason_codes, list) or not reason_codes or not all(
        isinstance(code, str) for code in reason_codes
    ):
        raise FollowupQueryPlanValidationError("reason_codes are required")
    unresolved_reason_codes = {
        code for issue in unresolved_issues for code in issue["reason_codes"]
    }
    if not set(reason_codes).issubset(unresolved_reason_codes):
        raise FollowupQueryPlanValidationError("reason code is not unresolved")
    if operation_kind == "SEARCH":
        _validate_constraint_delta(delta)
        if detail_candidate_ref is not None:
            raise FollowupQueryPlanValidationError("SEARCH cannot select a detail candidate")
    elif operation_kind == "DETAIL_FETCH":
        if delta is not None:
            raise FollowupQueryPlanValidationError("DETAIL_FETCH cannot change constraints")
        if (
            not isinstance(detail_candidate_ref, str)
            or detail_candidate_ref not in detail_candidate_refs
        ):
            raise FollowupQueryPlanValidationError("unknown detail candidate reference")
    elif delta is not None or detail_candidate_ref is not None:
        raise FollowupQueryPlanValidationError("operation carries forbidden follow-up fields")
    return cast(RouteQueryIntentV1, value)


def _validate_constraint_delta(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {"added_constraints", "removed_constraints"}:
        raise FollowupQueryPlanValidationError("SEARCH requires a constraint delta")
    added = value["added_constraints"]
    removed = value["removed_constraints"]
    if not isinstance(added, list) or not isinstance(removed, list) or not all(
        isinstance(item, str) for item in [*added, *removed]
    ) or not (added or removed):
        raise FollowupQueryPlanValidationError("SEARCH constraint delta is empty")
