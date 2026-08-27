"""Canonical Approval expiry transition."""

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1


def transition_expire_approval(
    *,
    action_status: ActionStatusV1,
    approval_status: ApprovalStatusV1,
    plan_status: PlanStatusV1,
    plan_is_current: bool,
) -> tuple[ActionStatusV1, ApprovalStatusV1]:
    authority_conflict = guard_current_plan_authority(
        plan_status=plan_status, plan_is_current=plan_is_current
    )
    if authority_conflict is not None:
        raise ValueError(authority_conflict)
    if (
        action_status is not ActionStatusV1.APPROVED
        or approval_status is not ApprovalStatusV1.ACTIVE
    ):
        raise ValueError("only an ACTIVE approval for an APPROVED action may expire")
    return ActionStatusV1.EXPIRED, ApprovalStatusV1.EXPIRED
