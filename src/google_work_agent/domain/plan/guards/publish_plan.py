"""Guard for publishing an approval-bearing write Plan."""

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def guard_publish_plan(
    run_status: RunStatusV1,
    plan_status: PlanStatusV1,
    *,
    review_status: PlanReviewStatus,
) -> None:
    if run_status is not RunStatusV1.PLANNING or plan_status is not PlanStatusV1.DRAFT:
        raise RunTransitionRejected("PublishPlan requires Run PLANNING and Plan DRAFT")
    if review_status is not PlanReviewStatus.PASSED:
        raise RunTransitionRejected("PublishPlan requires a current PASSED review")
