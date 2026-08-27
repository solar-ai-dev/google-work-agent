from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.finalize_read_action import (
    transition_finalize_read_action,
)


def test_finalize_read_action_moves_executed_to_verified() -> None:
    result = transition_finalize_read_action(
        ActionStatusV1.EXECUTED, 2, 2, effect_type=EffectType.READ
    )
    assert result.applied and result.current_status is ActionStatusV1.VERIFIED
