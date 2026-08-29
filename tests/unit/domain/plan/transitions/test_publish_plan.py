import pytest

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.plan.transitions.publish_plan import transition_publish_plan
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_publish_plan_closes_run_and_plan_pair() -> None:
    assert transition_publish_plan(
        RunStatusV1.PLANNING, PlanStatusV1.DRAFT, review_status=PlanReviewStatus.PASSED
    ) == (RunStatusV1.WAITING_APPROVAL, PlanStatusV1.WAITING_APPROVAL)


@pytest.mark.parametrize("review", [PlanReviewStatus.REQUIRED])
def test_publish_plan_requires_current_passed_review(review: PlanReviewStatus) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_publish_plan(RunStatusV1.PLANNING, PlanStatusV1.DRAFT, review_status=review)
