from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.cancel_pending_action import (
    transition_cancel_pending_action,
)
from google_work_agent.domain.plan.model import PlanStatus


def test_cancel_pending_action_closes_expired_action() -> None:
    result = transition_cancel_pending_action(
        ActionStatus.EXPIRED,
        4,
        4,
        effect_type=EffectType.DELETE,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatus.CANCELLED
