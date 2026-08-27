from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.refresh_expired_action import (
    transition_refresh_expired_action,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def test_refresh_expired_action_requires_fresh_review_before_reapproval() -> None:
    result = transition_refresh_expired_action(
        ActionStatusV1.EXPIRED,
        4,
        4,
        effect_type=EffectType.UPDATE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )
    assert result.applied and result.current_status is ActionStatusV1.MODIFIED
