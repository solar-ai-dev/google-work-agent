"""Plan domain model and lifecycle vocabulary."""

from dataclasses import dataclass
from enum import StrEnum


class PlanStatusV1(StrEnum):
    DRAFT = "DRAFT"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PlanReviewStatus(StrEnum):
    PASSED = "PASSED"
    REQUIRED = "REQUIRED"
    REVISE = "REVISE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    run_id: str
    revision_no: int
    status: PlanStatusV1
    summary_text: str | None
    created_at_ms: int
    review_status: PlanReviewStatus = PlanReviewStatus.PASSED
    review_version: int = 0
    review_disposition: str | None = None
