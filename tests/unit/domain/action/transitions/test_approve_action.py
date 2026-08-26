from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.approve_action import transition_approve_action
from google_work_agent.domain.plan.model import PlanStatus


def test_approve_action_requires_write_and_passed_review() -> None:
    rejected = transition_approve_action(
        ActionStatus.MODIFIED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=False,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    approved = transition_approve_action(
        ActionStatus.MODIFIED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    read = transition_approve_action(
        ActionStatus.PROPOSED,
        0,
        0,
        effect_type=EffectType.READ,
        plan_review_passed=True,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert not rejected.applied
    assert approved.applied and approved.current_status is ActionStatus.APPROVED
    assert not read.applied


def test_approve_action_rejects_superseded_plan_child() -> None:
    result = transition_approve_action(
        ActionStatus.PROPOSED,
        1,
        1,
        effect_type=EffectType.CREATE,
        plan_review_passed=True,
        plan_status=PlanStatus.SUPERSEDED,
        plan_is_current=False,
    )
    assert not result.applied
    assert result.conflict_detail == "superseded or noncurrent Plan children are history-only"
