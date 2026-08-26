from google_work_agent.domain.action.model import ActionStatus, EffectType
from google_work_agent.domain.action.transitions.claim_read_action import (
    transition_claim_read_action,
)


def test_claim_read_action_is_read_only() -> None:
    assert transition_claim_read_action(
        ActionStatus.PROPOSED, 0, 0, effect_type=EffectType.READ
    ).applied
    assert not transition_claim_read_action(
        ActionStatus.PROPOSED, 0, 0, effect_type=EffectType.CREATE
    ).applied
