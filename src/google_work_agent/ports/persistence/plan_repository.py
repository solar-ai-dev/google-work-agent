"""Plan persistence port."""

from typing import Protocol

from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1


class PlanRepository(Protocol):
    def get_by_id(self, plan_id: str) -> PlanRecord | None: ...
    def insert_draft(self, plan: PlanRecord) -> None: ...
    def update_if_status(
        self,
        plan_id: str,
        *,
        expected_status: PlanStatusV1,
        next_status: PlanStatusV1,
    ) -> PlanRecord | None: ...
    def update_review_if_version_and_status(
        self,
        plan_id: str,
        *,
        expected_review_version: int,
        expected_review_statuses: frozenset[PlanReviewStatus],
        values: dict[str, object],
    ) -> PlanRecord | None: ...
    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]: ...
