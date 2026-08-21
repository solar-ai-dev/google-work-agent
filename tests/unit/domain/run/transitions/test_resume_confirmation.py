import pytest
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.resume_confirmation import transition_resume_confirmation

def test_resume_confirmation_restores_registered_safe_phase():
    assert transition_resume_confirmation(RunStatus.WAITING_CONFIRMATION,resume_status=RunStatus.RETRIEVING) is RunStatus.RETRIEVING
    with pytest.raises(RunTransitionRejected):transition_resume_confirmation(RunStatus.WAITING_CONFIRMATION,resume_status=RunStatus.WAITING_APPROVAL)
