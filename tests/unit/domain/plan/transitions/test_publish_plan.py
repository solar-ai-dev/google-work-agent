import pytest

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatus
from google_work_agent.domain.plan.transitions.publish_plan import transition_publish_plan
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


def test_publish_plan_closes_run_and_plan_pair() -> None:
    assert transition_publish_plan(
        RunStatus.PLANNING, PlanStatus.DRAFT, review_status=PlanReviewStatus.PASSED
    ) == (RunStatus.WAITING_APPROVAL, PlanStatus.WAITING_APPROVAL)


@pytest.mark.parametrize("review", [PlanReviewStatus.REQUIRED, PlanReviewStatus.BLOCKED])
def test_publish_plan_requires_current_passed_review(review: PlanReviewStatus) -> None:
    with pytest.raises(RunTransitionRejected):
        transition_publish_plan(RunStatus.PLANNING, PlanStatus.DRAFT, review_status=review)
