import pytest

from google_work_agent.domain.run.guards.resume_confirmation import guard_resume_confirmation
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_resume_confirmation_restores_only_registered_safe_status() -> None:
    guard_resume_confirmation(
        RunStatusV1.WAITING_CONFIRMATION,
        resume_status=RunStatusV1.WAITING_APPROVAL,
    )
    with pytest.raises(RunTransitionRejected):
        guard_resume_confirmation(
            RunStatusV1.WAITING_CONFIRMATION,
            resume_status=RunStatusV1.COMPLETED,
        )
