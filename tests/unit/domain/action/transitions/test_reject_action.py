import pytest

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


@pytest.mark.parametrize("effect_type", [EffectType.CREATE, EffectType.READ])
@pytest.mark.parametrize("plan_status", list(PlanStatusV1))
def test_reject_action_exact_effect_plan_matrix(
    effect_type: EffectType, plan_status: PlanStatusV1
) -> None:
    result = transition_reject_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=effect_type,
        plan_status=plan_status,
        plan_is_current=True,
    )
    expected = (
        PlanStatusV1.ACTIVE if effect_type is EffectType.READ else PlanStatusV1.WAITING_APPROVAL
    )
    assert result.applied is (plan_status is expected)
