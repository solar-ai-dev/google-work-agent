from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.prepare_write_retry import (
    transition_prepare_write_retry,
)
from google_work_agent.domain.plan.model import PlanStatusV1


def test_prepare_write_retry_preserves_the_stronger_write_only_guard() -> None:
    result = transition_prepare_write_retry(
        ActionStatusV1.FAILED,
        current_version=2,
        expected_version=2,
        effect_type=EffectType.CREATE,
        plan_status=PlanStatusV1.WAITING_APPROVAL,
        plan_is_current=True,
    )

    assert result.applied is True
    assert result.current_status is ActionStatusV1.MODIFIED
