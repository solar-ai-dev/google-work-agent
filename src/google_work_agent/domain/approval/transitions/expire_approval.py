"""Canonical Approval expiry transition."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatus
from google_work_agent.domain.approval.model import ApprovalStatus
from google_work_agent.domain.plan.model import PlanStatus


def transition_expire_approval(
    *,
    action_status: ActionStatus,
    approval_status: ApprovalStatus,
    plan_status: PlanStatus,
    plan_is_current: bool,
) -> tuple[ActionStatus, ApprovalStatus]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status, plan_is_current=plan_is_current
    )
    if authority_conflict is not None:
        raise ValueError(authority_conflict)
    if action_status is not ActionStatus.APPROVED or approval_status is not ApprovalStatus.ACTIVE:
        raise ValueError("only an ACTIVE approval for an APPROVED action may expire")
    return ActionStatus.EXPIRED, ApprovalStatus.EXPIRED
