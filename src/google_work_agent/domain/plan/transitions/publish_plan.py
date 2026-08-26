"""Publish an approval-bearing write Plan."""

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatus
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


def transition_publish_plan(
    run_status: RunStatus,
    plan_status: PlanStatus,
    *,
    review_status: PlanReviewStatus,
) -> tuple[RunStatus, PlanStatus]:
    if run_status is not RunStatus.PLANNING or plan_status is not PlanStatus.DRAFT:
        raise RunTransitionRejected("PublishPlan requires Run PLANNING and Plan DRAFT")
    if review_status is not PlanReviewStatus.PASSED:
        raise RunTransitionRejected("PublishPlan requires a current PASSED review")
    return RunStatus.WAITING_APPROVAL, PlanStatus.WAITING_APPROVAL
