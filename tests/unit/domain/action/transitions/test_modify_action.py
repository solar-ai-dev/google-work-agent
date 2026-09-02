import pytest

from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.modify_action import transition_modify_action
from google_work_agent.domain.plan.model import PlanStatusV1


def test_modify_action__moves_approved__to_modified() -> None:
    result = transition_modify_action(
        ActionStatusV1.APPROVED,
        2,
        2,
        effect_type=EffectType.UPDATE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatusV1.MODIFIED


@pytest.mark.parametrize("plan_status", list(PlanStatusV1))
def test_modify_action__requires_current__waiting_write_plan(plan_status: PlanStatusV1) -> None:
    result = transition_modify_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=EffectType.CREATE,
        plan_status=plan_status,
        plan_is_current=True,
    )
    assert result.applied is (plan_status is PlanStatusV1.WAITING_APPROVAL)


def test_modify_action__rejects_legacy__read() -> None:
    result = transition_modify_action(
        ActionStatusV1.PROPOSED,
        0,
        0,
        effect_type=EffectType.READ,
        plan_status=PlanStatusV1.ACTIVE,
        plan_is_current=True,
    )
    assert not result.applied
