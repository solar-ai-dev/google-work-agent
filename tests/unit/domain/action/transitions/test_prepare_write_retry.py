from google_work_agent.domain.action.transitions.prepare_write_retry import (
    transition_prepare_write_retry,
)
from google_work_agent.domain.enums import ActionStatus, EffectType


def test_prepare_write_retry_preserves_the_stronger_write_only_guard() -> None:
    result = transition_prepare_write_retry(
        ActionStatus.FAILED, current_version=2, expected_version=2, effect_type=EffectType.CREATE
    )

    assert result.applied is True
    assert result.current_status is ActionStatus.MODIFIED
