"""Deterministic insufficient-data safety decision shared by every graph profile."""

from dataclasses import dataclass
from enum import StrEnum


class ResolutionSource(StrEnum):
    USER = "USER"
    GOOGLE = "GOOGLE"
    POLICY = "POLICY"
    ROUTE = "ROUTE"


class InsufficientDataDisposition(StrEnum):
    CONTINUE = "CONTINUE"
    BLOCKED = "BLOCKED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    PARTIAL = "PARTIAL"


@dataclass(frozen=True, slots=True)
class InsufficientDataIssue:
    issue_type: str
    required: bool
    resolution_source: ResolutionSource
    safety_critical: bool = False


@dataclass(frozen=True, slots=True)
class InsufficientDataContext:
    issues: tuple[InsufficientDataIssue, ...]
    budget_remaining: int
    read_only: bool
    evidence_supported_partial_possible: bool
    write_required_data_missing: bool = False
    user_can_resolve_write_gap: bool = False


def decide_insufficient_data(context: InsufficientDataContext) -> InsufficientDataDisposition:
    """Apply the canonical fail-closed precedence independently of LLM confidence."""

    required = tuple(issue for issue in context.issues if issue.required)
    if any(
        issue.safety_critical or issue.resolution_source is ResolutionSource.POLICY
        for issue in required
    ):
        return InsufficientDataDisposition.BLOCKED
    if any(issue.resolution_source is ResolutionSource.USER for issue in required):
        return InsufficientDataDisposition.NEEDS_CONFIRMATION
    if any(issue.resolution_source is ResolutionSource.ROUTE for issue in required):
        return InsufficientDataDisposition.ROUTE_RECONSIDERATION_REQUIRED
    if (
        any(issue.resolution_source is ResolutionSource.GOOGLE for issue in required)
        and context.budget_remaining > 0
    ):
        return InsufficientDataDisposition.RETRIEVE_MORE
    if (
        context.budget_remaining <= 0
        and context.read_only
        and context.evidence_supported_partial_possible
    ):
        return InsufficientDataDisposition.PARTIAL
    if context.write_required_data_missing:
        if context.user_can_resolve_write_gap:
            return InsufficientDataDisposition.NEEDS_CONFIRMATION
        return InsufficientDataDisposition.BLOCKED
    if required:
        return InsufficientDataDisposition.BLOCKED
    return InsufficientDataDisposition.CONTINUE
