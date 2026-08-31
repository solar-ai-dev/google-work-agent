"""Canonical Approval expiry transition."""

from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.guards.expire_approval import (
    ApprovalExpiryInput,
    guard_expire_approval,
)
from google_work_agent.domain.approval.model import ApprovalStatusV1


def transition_expire_approval(
    value: ApprovalExpiryInput,
) -> tuple[ActionStatusV1, ApprovalStatusV1]:
    guard_expire_approval(value)
    return ActionStatusV1.EXPIRED, ApprovalStatusV1.EXPIRED


__all__ = ["transition_expire_approval"]
