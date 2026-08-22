import pytest

from google_work_agent.domain.action.transitions.cancel_pending_action import transition_cancel_pending_action
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.action.transitions.prepare_write_retry import transition_prepare_write_retry
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.approval.transitions.approve_action import transition_approve_action
from google_work_agent.domain.claim.guards.claim_execution import ClaimExecutionGuardInput, guard_claim_execution
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution
from google_work_agent.domain.enums import ActionStatus, ApprovalStatus, EffectType, RunStatus
from google_work_agent.domain.exceptions import PolicyViolationError


def test_action_lifecycle_canonical_transitions():
    modified = transition_modify_action(ActionStatus.APPROVED, 2, 2, effect_type=EffectType.UPDATE)
    assert modified.applied and modified.current_status is ActionStatus.MODIFIED and modified.current_version == 3
    rejected = transition_reject_action(ActionStatus.APPROVED, 2, 2, effect_type=EffectType.SEND)
    assert rejected.applied and rejected.current_status is ActionStatus.REJECTED
    cancelled = transition_cancel_pending_action(ActionStatus.EXPIRED, 4, 4, effect_type=EffectType.DELETE)
    assert cancelled.applied and cancelled.current_status is ActionStatus.CANCELLED
    retry = transition_prepare_write_retry(ActionStatus.FAILED, 5, 5, effect_type=EffectType.CREATE)
    assert retry.applied and retry.current_status is ActionStatus.MODIFIED


def test_approval_requires_write_and_passed_review():
    blocked = transition_approve_action(ActionStatus.MODIFIED, 1, 1, effect_type=EffectType.CREATE, plan_review_passed=False)
    assert not blocked.applied
    approved = transition_approve_action(ActionStatus.MODIFIED, 1, 1, effect_type=EffectType.CREATE, plan_review_passed=True)
    assert approved.applied and approved.current_status is ActionStatus.APPROVED
    read = transition_approve_action(ActionStatus.PROPOSED, 0, 0, effect_type=EffectType.READ, plan_review_passed=True)
    assert not read.applied


def _claim_guard(**changes):
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
        durable_cancel_intent=False,
        plan_superseded=False,
        predecessor_verified=True,
        active_attempt_exists=False,
    )
    values.update(changes)
    return ClaimExecutionGuardInput(**values)


def test_claim_guard_preserves_freshness_cancel_and_dependency_safety():
    guard_claim_execution(_claim_guard())
    for changes in (
        {"approval_arguments_hash": "stale"},
        {"now_ms": 200},
        {"durable_cancel_intent": True},
        {"plan_superseded": True},
        {"predecessor_verified": False},
        {"active_attempt_exists": True},
    ):
        with pytest.raises(PolicyViolationError):
            guard_claim_execution(_claim_guard(**changes))


def test_claim_transition_is_write_only_and_version_checked():
    claimed = transition_claim_execution(ActionStatus.APPROVED, 7, 7, effect_type=EffectType.SEND)
    assert claimed.applied and claimed.current_status is ActionStatus.EXECUTING and claimed.current_version == 8
    assert not transition_claim_execution(ActionStatus.APPROVED, 7, 6, effect_type=EffectType.SEND).applied
    assert not transition_claim_execution(ActionStatus.APPROVED, 7, 7, effect_type=EffectType.READ).applied
