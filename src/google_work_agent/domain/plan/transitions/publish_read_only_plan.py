"""Publish a legacy READ-only Plan."""

from google_work_agent.domain.plan.guards.publish_read_only_plan import (
    guard_publish_read_only_plan,
)
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


def transition_publish_read_only_plan(
    run_status: RunStatusV1,
    plan_status: PlanStatusV1,
    *,
    review_status: PlanReviewStatus,
) -> tuple[RunStatusV1, PlanStatusV1]:
    guard_publish_read_only_plan(run_status, plan_status, review_status=review_status)
    return RunStatusV1.EXECUTING, PlanStatusV1.ACTIVE
