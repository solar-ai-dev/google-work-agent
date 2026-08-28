import pytest

from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.cancel_pending_action import (
    transition_cancel_pending_action,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def test_cancel_pending_action_closes_expired_action() -> None:
    result = transition_cancel_pending_action(
        ActionStatusV1.EXPIRED,
        4,
        4,
        effect_type=EffectType.DELETE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatusV1.CANCELLED


@pytest.mark.parametrize("effect_type", [EffectType.CREATE, EffectType.READ])
@pytest.mark.parametrize("plan_status", list(PlanStatusV1))
def test_cancel_pending_action_exact_effect_plan_matrix(
    effect_type: EffectType, plan_status: PlanStatusV1
) -> None:
    result = transition_cancel_pending_action(
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
