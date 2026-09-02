import pytest

from google_work_agent.domain.run.guards.resume_after_reauth import guard_resume_after_reauth
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def _guard(current_status: RunStatusV1, *, resume_status: RunStatusV1) -> None:
    guard_resume_after_reauth(
        current_status,
        resume_status=resume_status,
        target_kind="MAIN_CONTROL",
        target_stage="PREFLIGHT",
        binding_is_current=True,
        action_statuses=(),
        attempt_statuses=(),
        delivery_uncertain=False,
        cancel_intent_active=False,
    )


def test_resume_after__reauth_requires__safe_persisted_phase() -> None:
    _guard(RunStatusV1.REAUTH_REQUIRED, resume_status=RunStatusV1.WAITING_APPROVAL)
    with pytest.raises(RunTransitionRejected):
        _guard(RunStatusV1.VERIFYING, resume_status=RunStatusV1.WAITING_APPROVAL)
    with pytest.raises(RunTransitionRejected):
        _guard(RunStatusV1.REAUTH_REQUIRED, resume_status=RunStatusV1.COMPLETED)
