"""Canonical Approval expiry transition."""

from google_work_agent.domain.enums import ActionStatus, ApprovalStatus


def transition_expire_approval(*, action_status: ActionStatus, approval_status: ApprovalStatus) -> tuple[ActionStatus, ApprovalStatus]:
    if action_status is not ActionStatus.APPROVED or approval_status is not ApprovalStatus.ACTIVE:
        raise ValueError("only an ACTIVE approval for an APPROVED action may expire")
    return ActionStatus.EXPIRED, ApprovalStatus.EXPIRED
