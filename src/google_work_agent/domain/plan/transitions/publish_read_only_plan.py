"""Publish a legacy READ-only Plan."""

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def transition_publish_read_only_plan(
    run_status: RunStatusV1,
    plan_status: PlanStatusV1,
    *,
    review_status: PlanReviewStatus,
) -> tuple[RunStatusV1, PlanStatusV1]:
    if run_status is not RunStatusV1.PLANNING or plan_status is not PlanStatusV1.DRAFT:
        raise RunTransitionRejected("PublishReadOnlyPlan requires Run PLANNING and Plan DRAFT")
    if review_status is not PlanReviewStatus.PASSED:
        raise RunTransitionRejected("PublishReadOnlyPlan requires a current PASSED review")
    return RunStatusV1.EXECUTING, PlanStatusV1.ACTIVE
