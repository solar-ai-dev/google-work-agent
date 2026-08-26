from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatus
from google_work_agent.domain.plan.transitions.publish_read_only_plan import (
    transition_publish_read_only_plan,
)
from google_work_agent.domain.run.model import RunStatus


def test_publish_read_only_plan_activates_legacy_read_path() -> None:
    assert transition_publish_read_only_plan(
        RunStatus.PLANNING, PlanStatus.DRAFT, review_status=PlanReviewStatus.PASSED
    ) == (RunStatus.EXECUTING, PlanStatus.ACTIVE)
