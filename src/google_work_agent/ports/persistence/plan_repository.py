"""Plan persistence port."""

from typing import Protocol

from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1


class PlanRepository(Protocol):
    def load_bundle(self, plan_id: str) -> PlanRecord | None: ...
    def get_current(self, run_id: str) -> PlanRecord | None: ...
    def insert_revision(self, plan: PlanRecord) -> None: ...
    def update_if_version_and_status(
        self,
        plan_id: str,
        expected_version: int,
        expected_statuses: frozenset[PlanStatusV1],
        values: dict[str, object],
    ) -> bool: ...
    def record_review_result(
        self,
        plan_id: str,
        *,
        expected_review_version: int,
        expected_review_statuses: frozenset[PlanReviewStatus],
        values: dict[str, object],
    ) -> PlanRecord | None: ...


def current_plan_tuple(repository: PlanRepository, run_id: str) -> tuple[PlanRecord, ...]:
    current = repository.get_current(run_id)
    return () if current is None else (current,)
