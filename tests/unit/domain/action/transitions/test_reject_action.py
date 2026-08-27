from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.reject_action import transition_reject_action
from google_work_agent.domain.plan.model import PlanStatusV1


def test_reject_action_closes_approved_write() -> None:
    result = transition_reject_action(
        ActionStatusV1.APPROVED,
        2,
        2,
        effect_type=EffectType.SEND,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatusV1.REJECTED
