import pytest

from google_work_agent.domain.action.model import ActionStatusV1, EffectType, PolicyViolationError
from google_work_agent.domain.approval.model import ApprovalStatusV1
from google_work_agent.domain.claim.guards.claim_execution import (
    ClaimExecutionGuardInput,
    guard_claim_execution,
)
from google_work_agent.domain.plan.model import PlanStatusV1
from google_work_agent.domain.run.model import RunStatusV1


def _guard(**changes: object) -> ClaimExecutionGuardInput:
    values = {
        "action_status": ActionStatusV1.APPROVED,
        "effect_type": EffectType.UPDATE,
        "action_version": 3,
        "approval_status": ApprovalStatusV1.ACTIVE,
        "approval_action_version": 3,
        "approval_arguments_hash": "a",
        "current_arguments_hash": "a",
        "approval_source_snapshot_hash": "s",
        "current_source_snapshot_hash": "s",
        "approval_policy_version": "p",
        "current_policy_version": "p",
        "approval_tool_schema_version": "t",
        "current_tool_schema_version": "t",
        "expires_at_ms": 200,
        "now_ms": 100,
        "run_status": RunStatusV1.WAITING_APPROVAL,
        "plan_status": PlanStatusV1.WAITING_APPROVAL,
        "plan_is_current": True,
        "durable_cancel_intent": False,
        "predecessor_verified": True,
        "active_attempt_exists": False,
    }
    values.update(changes)
    return ClaimExecutionGuardInput(**values)  # type: ignore[arg-type]


def test_claim_execution_accepts__exact_safe_facts__and_rejects_each_boundary() -> None:
    guard_claim_execution(_guard())
    invalid = (
        {"effect_type": EffectType.READ},
        {"action_status": ActionStatusV1.PROPOSED},
        {"approval_status": ApprovalStatusV1.REVOKED},
        {"approval_action_version": 2},
        {"current_arguments_hash": "other"},
        {"current_source_snapshot_hash": "other"},
        {"current_policy_version": "other"},
        {"current_tool_schema_version": "other"},
        {"now_ms": 200},
        {"plan_is_current": False},
        {"plan_status": PlanStatusV1.SUPERSEDED},
        {"run_status": RunStatusV1.PLANNING},
        {"durable_cancel_intent": True},
        {"predecessor_verified": False},
        {"active_attempt_exists": True},
    )
    for change in invalid:
        with pytest.raises(PolicyViolationError):
            guard_claim_execution(_guard(**change))
