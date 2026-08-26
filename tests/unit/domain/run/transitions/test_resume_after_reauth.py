import pytest

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_after_reauth import (
    transition_resume_after_reauth,
)


def test_resume_after_reauth_restores_persisted_safe_phase() -> None:
    assert (
        transition_resume_after_reauth(
            RunStatus.REAUTH_REQUIRED,
            resume_status=RunStatus.VERIFYING,
        )
        is RunStatus.VERIFYING
    )


def test_resume_after_reauth_rejects_non_reauth_source() -> None:
    with pytest.raises(RunTransitionRejected):
        transition_resume_after_reauth(
            RunStatus.PLANNING,
            resume_status=RunStatus.VERIFYING,
        )
