"""Canonical Approval consumption transition."""

from google_work_agent.domain.enums import ApprovalStatus


def transition_consume_approval(approval_status: ApprovalStatus) -> ApprovalStatus:
    if approval_status is not ApprovalStatus.ACTIVE:
        raise ValueError("only an ACTIVE approval may be consumed")
    return ApprovalStatus.CONSUMED
