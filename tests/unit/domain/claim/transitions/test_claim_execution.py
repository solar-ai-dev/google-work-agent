import pytest

from google_work_agent.domain.action.model import ActionStatus, EffectType, PolicyViolationError
from google_work_agent.domain.approval.model import ApprovalStatus
from google_work_agent.domain.claim.guards.claim_execution import (
    ClaimExecutionGuardInput,
    guard_claim_execution,
)
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.plan.model import PlanStatus
from google_work_agent.domain.run.model import RunStatus


def _guard(**changes: object) -> ClaimExecutionGuardInput:
    values = dict(
        action_status=ActionStatus.APPROVED,
        effect_type=EffectType.UPDATE,
        action_version=3,
        approval_status=ApprovalStatus.ACTIVE,
        approval_action_version=3,
        approval_arguments_hash="a",
        current_arguments_hash="a",
        approval_source_snapshot_hash="s",
        current_source_snapshot_hash="s",
        approval_policy_version="p",
        current_policy_version="p",
        approval_tool_schema_version="t",
        current_tool_schema_version="t",
        expires_at_ms=200,
        now_ms=100,
        run_status=RunStatus.WAITING_APPROVAL,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
        durable_cancel_intent=False,
        predecessor_verified=True,
        active_attempt_exists=False,
    )
    values.update(changes)
    return ClaimExecutionGuardInput(**values)


def test_claim_execution_requires_current_plan_and_legal_parent_run() -> None:
    guard_claim_execution(_guard())
    for change in (
        {"plan_is_current": False},
        {"plan_status": PlanStatus.SUPERSEDED},
        {"run_status": RunStatus.PLANNING},
        {"durable_cancel_intent": True},
    ):
        with pytest.raises(PolicyViolationError):
            guard_claim_execution(_guard(**change))
    assert transition_claim_execution(
        ActionStatus.APPROVED, 3, 3, effect_type=EffectType.UPDATE
    ).applied
