from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.plan.model import PlanStatus


def test_modify_action_moves_approved_to_modified() -> None:
    result = transition_modify_action(
        ActionStatus.APPROVED,
        2,
        2,
        effect_type=EffectType.UPDATE,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatus.MODIFIED
