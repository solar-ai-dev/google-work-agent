import pytest

from google_work_agent.domain.run.guards.require_reauth import guard_require_reauth
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def _guard(**changes: object) -> None:
    values = {
        "target_kind": "MAIN_CONTROL",
        "target_stage": "PREFLIGHT",
        "binding_is_current": True,
        "action_statuses": (),
        "attempt_statuses": (),
        "has_legacy_read_executing": False,
        "delivery_uncertain": False,
        "cancel_intent_active": False,
    }
    values.update(changes)
    guard_require_reauth(RunStatusV1.WAITING_APPROVAL, **values)  # type: ignore[arg-type]


def test_require_reauth_requires_registered_target_and_phase_facts() -> None:
    _guard()
    with pytest.raises(RunTransitionRejected):
        _guard(binding_is_current=False)
    with pytest.raises(RunTransitionRejected):
        _guard(target_stage="UNKNOWN")
