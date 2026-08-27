from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.plan.transitions.publish_read_only_plan import (
    transition_publish_read_only_plan,
)
from google_work_agent.domain.run.model import RunStatusV1


def test_publish_read_only_plan_activates_legacy_read_path() -> None:
    assert transition_publish_read_only_plan(
        RunStatusV1.PLANNING, PlanStatusV1.DRAFT, review_status=PlanReviewStatus.PASSED
    ) == (RunStatusV1.EXECUTING, PlanStatusV1.ACTIVE)
