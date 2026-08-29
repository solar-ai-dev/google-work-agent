"""Canonical Approval expiry transition."""

from dataclasses import dataclass

from google_work_agent.domain.action.guards.current_plan_authority import (
    guard_current_plan_authority,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.plan.model import PlanStatusV1

_ALLOWED_PLAN_STATUSES = frozenset({PlanStatusV1.WAITING_APPROVAL})


@dataclass(frozen=True, slots=True)
class ApprovalExpiryInput:
    """Current authority facts used to prove that an Approval is stale."""

    action_status: ActionStatusV1
    action_version: int
    current_arguments_hash: str
    approval_status: ApprovalStatusV1
    approval_action_version: int
    approval_arguments_hash: str
    approval_source_snapshot_hash: str
    current_source_snapshot_hash: str
    approval_policy_version: str
    current_policy_version: str
    approval_tool_schema_version: str
    current_tool_schema_version: str
    expires_at_ms: int
    now_ms: int
    plan_status: PlanStatusV1
    plan_is_current: bool


def transition_expire_approval(
    value: ApprovalExpiryInput,
) -> tuple[ActionStatusV1, ApprovalStatusV1]:
    authority_conflict = guard_current_plan_authority(
        plan_status=value.plan_status,
        plan_is_current=value.plan_is_current,
        allowed_statuses=_ALLOWED_PLAN_STATUSES,
    )
    if authority_conflict is not None:
        raise ValueError(authority_conflict)
    if (
        value.action_status is not ActionStatusV1.APPROVED
        or value.approval_status is not ApprovalStatusV1.ACTIVE
    ):
        raise ValueError("only an ACTIVE approval for an APPROVED action may expire")

    stale_reasons = (
        value.now_ms >= value.expires_at_ms,
        value.action_version != value.approval_action_version,
        value.current_arguments_hash != value.approval_arguments_hash,
        value.current_source_snapshot_hash != value.approval_source_snapshot_hash,
        value.current_policy_version != value.approval_policy_version,
        value.current_tool_schema_version != value.approval_tool_schema_version,
    )
    if not any(stale_reasons):
        raise ValueError("a still-current ACTIVE approval cannot be expired")
    return ActionStatusV1.EXPIRED, ApprovalStatusV1.EXPIRED


__all__ = ["ApprovalExpiryInput", "transition_expire_approval"]
