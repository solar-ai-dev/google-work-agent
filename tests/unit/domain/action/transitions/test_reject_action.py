from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.plan.model import PlanStatus


def test_reject_action_closes_approved_write() -> None:
    result = transition_reject_action(
        ActionStatus.APPROVED,
        2,
        2,
        effect_type=EffectType.SEND,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatus.REJECTED
