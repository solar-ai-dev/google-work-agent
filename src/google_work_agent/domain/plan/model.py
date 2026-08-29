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


PLAN_REVIEW_DISPOSITIONS = frozenset(
    {"PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"}
)


@dataclass(frozen=True, slots=True)
class Plan:
    id: str
    run_id: str
    revision_no: int
    status: PlanStatusV1
    summary_text: str | None
    created_at_ms: int
    review_status: PlanReviewStatus = PlanReviewStatus.REQUIRED
    review_version: int = 0
    review_disposition: str | None = None

    def __post_init__(self) -> None:
        if (
            self.review_disposition is not None
            and self.review_disposition not in PLAN_REVIEW_DISPOSITIONS
        ):
            raise ValueError("review disposition is outside the canonical closed set")
        if self.review_status is PlanReviewStatus.PASSED:
            if self.review_disposition != "PASS":
                raise ValueError("PASSED review gate requires PASS disposition")
            return
        if self.review_disposition == "PASS":
            raise ValueError("PASS disposition requires PASSED review gate")
