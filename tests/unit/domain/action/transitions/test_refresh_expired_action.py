from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.refresh_expired_action import (
    transition_refresh_expired_action,
)
from google_work_agent.domain.plan.model import PlanStatus


def test_refresh_expired_action_requires_fresh_review_before_reapproval() -> None:
    result = transition_refresh_expired_action(
        ActionStatus.EXPIRED,
        4,
        4,
        effect_type=EffectType.UPDATE,
        plan_status=PlanStatus.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatus.MODIFIED
