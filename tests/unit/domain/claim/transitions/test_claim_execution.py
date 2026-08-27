import pytest

from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.claim.guards.claim_execution import (
    ClaimExecutionGuardInput,
    guard_claim_execution,
)
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


def _guard(**changes: object) -> ClaimExecutionGuardInput:
    values = dict(
        action_status=ActionStatusV1.APPROVED,
        effect_type=EffectType.UPDATE,
        action_version=3,
        approval_status=ApprovalStatusV1.ACTIVE,
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
        run_status=RunStatusV1.WAITING_APPROVAL,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
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
        {"plan_status": PlanStatusV1.SUPERSEDED},
        {"run_status": RunStatusV1.PLANNING},
        {"durable_cancel_intent": True},
    ):
        with pytest.raises(PolicyViolationError):
            guard_claim_execution(_guard(**change))
    assert transition_claim_execution(
        ActionStatusV1.APPROVED, 3, 3, effect_type=EffectType.UPDATE
    ).applied
