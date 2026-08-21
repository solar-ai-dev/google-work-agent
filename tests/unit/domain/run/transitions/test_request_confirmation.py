from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.request_confirmation import transition_request_confirmation

def test_request_confirmation_applies_canonical_transition(): assert transition_request_confirmation(RunStatus.ANALYZING) is RunStatus.WAITING_CONFIRMATION
def test_request_confirmation_rejects_unrelated_status():
    try: transition_request_confirmation(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
