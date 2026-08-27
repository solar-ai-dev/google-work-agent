from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.plan.model import PlanStatusV1


def test_modify_action_moves_approved_to_modified() -> None:
    result = transition_modify_action(
        ActionStatusV1.APPROVED,
        2,
        2,
        effect_type=EffectType.UPDATE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatusV1.MODIFIED
