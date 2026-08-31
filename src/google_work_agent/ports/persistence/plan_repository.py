"""Plan persistence port and bounded aggregate read projection."""

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.domain.action.model import Action, ActionDependency, ActionEvidence
from google_work_agent.domain.evidence.model import Evidence
from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1


@dataclass(frozen=True, slots=True)
class PlanBundle:
    plan: PlanRecord
    actions: tuple[Action, ...]
    dependencies: tuple[ActionDependency, ...]
    evidence: tuple[Evidence, ...]
    action_evidence: tuple[ActionEvidence, ...]


class PlanRepository(Protocol):
    def load_bundle(self, plan_id: str) -> PlanBundle | None: ...
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
