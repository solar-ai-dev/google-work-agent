"""Shared child-authority fence for mutable Action lifecycle commands."""

from google_work_agent.domain.plan.model import PlanStatus


def guard_current_plan_authority(*, plan_status: PlanStatus, plan_is_current: bool) -> str | None:
    if plan_status is PlanStatus.SUPERSEDED or not plan_is_current:
        return "superseded or noncurrent Plan children are history-only"
    return None
