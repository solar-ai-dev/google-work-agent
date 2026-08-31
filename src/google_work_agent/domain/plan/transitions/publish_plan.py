"""Publish an approval-bearing write Plan."""

from google_work_agent.domain.plan.guards.publish_plan import guard_publish_plan
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


def transition_publish_plan(
    run_status: RunStatusV1,
    plan_status: PlanStatusV1,
    *,
    review_status: PlanReviewStatus,
) -> tuple[RunStatusV1, PlanStatusV1]:
    guard_publish_plan(run_status, plan_status, review_status=review_status)
    return RunStatusV1.WAITING_APPROVAL, PlanStatusV1.WAITING_APPROVAL
