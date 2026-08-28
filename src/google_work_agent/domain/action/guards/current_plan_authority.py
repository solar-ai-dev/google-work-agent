"""Shared child-authority fence for mutable Action lifecycle commands."""

from google_work_agent.domain.plan.model import PlanStatusV1


def guard_current_plan_authority(
    *,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
    allowed_statuses: frozenset[PlanStatusV1],
) -> str | None:
    if plan_status is PlanStatusV1.SUPERSEDED or not plan_is_current:
        return "superseded or noncurrent Plan children are history-only"
    if plan_status not in allowed_statuses:
        allowed = "|".join(sorted(status.value for status in allowed_statuses))
        return f"Plan status must be {allowed} for this child mutation"
    return None
