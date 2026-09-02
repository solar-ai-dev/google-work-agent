from google_work_agent.domain.action.model import ActionStatusV1, EffectType
from google_work_agent.domain.claim.transitions.claim_execution import transition_claim_execution


def test_claim_execution__applies_the__versioned_action_transition() -> None:
    assert transition_claim_execution(
        ActionStatusV1.APPROVED, 3, 3, effect_type=EffectType.UPDATE
    ).applied
