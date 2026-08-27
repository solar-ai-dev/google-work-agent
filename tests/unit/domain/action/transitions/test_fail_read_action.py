from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.action.transitions.fail_read_action import transition_fail_read_action


def test_fail_read_action_moves_executing_to_failed() -> None:
    result = transition_fail_read_action(
        ActionStatusV1.EXECUTING, 1, 1, effect_type=EffectType.READ
    )
    assert result.applied and result.current_status is ActionStatusV1.FAILED
