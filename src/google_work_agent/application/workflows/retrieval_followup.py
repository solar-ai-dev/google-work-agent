"""Deterministic validation for bounded Retrieval follow-up operations."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.application.workflows.api_acquisition import retrieval_query_hash
from google_work_agent.application.workflows.handoff_contracts import (
    SourceFetchPlanV1,
    SufficiencyIssueV2,
)
from google_work_agent.application.workflows.retrieval_read_cache import (
    DetailTargetCacheEntry,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2


class FollowupValidationError(ValueError):
    """A planner proposal is not safe to execute as a local Retrieval read."""


@dataclass(frozen=True, slots=True)
class ChangedSearchProposal:
    route_id: str
    plan: SourceFetchPlanV1
    previous_query_hash: str
    added_constraints: tuple[str, ...]
    removed_constraints: tuple[str, ...]
    change_reason_code: str


def validate_changed_search(
    *,
    proposal: ChangedSearchProposal,
    frozen_route: ToolRoutePlanV2,
    unresolved_issues: list[SufficiencyIssueV2],
) -> str:
    """Return new semantic query identity or fail before a connector read."""
    route = next(
        (
            item
            for item in frozen_route["input_plan"]["input_routes"]
            if item["route_id"] == proposal.route_id
        ),
        None,
    )
    if route is None:
        raise FollowupValidationError("ROUTE_RECONSIDERATION_REQUIRED")
    if not any(proposal.change_reason_code in issue["reason_codes"] for issue in unresolved_issues):
        raise FollowupValidationError("CHANGE_REASON_NOT_LINKED_TO_SUFFICIENCY_ISSUE")
    new_query_hash = retrieval_query_hash(proposal.plan)
    has_semantic_change = bool(proposal.added_constraints or proposal.removed_constraints)
    if not has_semantic_change and new_query_hash == proposal.previous_query_hash:
        raise FollowupValidationError("QUERY_REPEATED_WITHOUT_CHANGE")
    return new_query_hash


def validate_detail_fetch(
    *, target: DetailTargetCacheEntry,
    frozen_route: ToolRoutePlanV2,
    unresolved_issues: list[SufficiencyIssueV2],
    change_reason_code: str,
    remaining_details: int,
) -> None:
    if remaining_details <= 0:
        raise FollowupValidationError("DETAIL_BUDGET_EXHAUSTED")
    if not any(change_reason_code in issue["reason_codes"] for issue in unresolved_issues):
        raise FollowupValidationError("CHANGE_REASON_NOT_LINKED_TO_SUFFICIENCY_ISSUE")
    route = next(
        (
            item
            for item in frozen_route["input_plan"]["input_routes"]
            if item["route_id"] == target.route_id
        ),
        None,
    )
    if route is None:
        raise FollowupValidationError("ROUTE_RECONSIDERATION_REQUIRED")
    if target.detail_tool_id not in route["allowed_read_tool_ids"]:
        raise FollowupValidationError("DETAIL_TOOL_NOT_ALLOWED")
