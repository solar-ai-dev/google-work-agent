"""Guard for publishing a legacy READ-only Plan."""

from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def guard_publish_read_only_plan(
    run_status: RunStatusV1,
    plan_status: PlanStatusV1,
    *,
    review_status: PlanReviewStatus,
) -> None:
    if run_status is not RunStatusV1.PLANNING or plan_status is not PlanStatusV1.DRAFT:
        raise RunTransitionRejected("PublishReadOnlyPlan requires Run PLANNING and Plan DRAFT")
    if review_status is not PlanReviewStatus.PASSED:
        raise RunTransitionRejected("PublishReadOnlyPlan requires a current PASSED review")
