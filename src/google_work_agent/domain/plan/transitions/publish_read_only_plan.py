"""Publish a legacy READ-only Plan."""

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatus
from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected


def transition_publish_read_only_plan(
    run_status: RunStatus,
    plan_status: PlanStatus,
    *,
    review_status: PlanReviewStatus,
) -> tuple[RunStatus, PlanStatus]:
    if run_status is not RunStatus.PLANNING or plan_status is not PlanStatus.DRAFT:
        raise RunTransitionRejected("PublishReadOnlyPlan requires Run PLANNING and Plan DRAFT")
    if review_status is not PlanReviewStatus.PASSED:
        raise RunTransitionRejected("PublishReadOnlyPlan requires a current PASSED review")
    return RunStatus.EXECUTING, PlanStatus.ACTIVE
