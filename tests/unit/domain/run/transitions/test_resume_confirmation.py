from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.domain.run.transitions.resume_confirmation import (
    transition_resume_confirmation,
)


def test_resume_confirmation_restores_registered_safe_phase() -> None:
    assert (
        transition_resume_confirmation(
            RunStatusV1.WAITING_CONFIRMATION, resume_status=RunStatusV1.RETRIEVING
        )
        is RunStatusV1.RETRIEVING
    )
    assert (
        transition_resume_confirmation(
            RunStatusV1.WAITING_CONFIRMATION, resume_status=RunStatusV1.WAITING_APPROVAL
        )
        is RunStatusV1.WAITING_APPROVAL
    )
