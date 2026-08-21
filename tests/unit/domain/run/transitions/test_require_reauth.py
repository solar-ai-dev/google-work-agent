from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.require_reauth import transition_require_reauth

def test_require_reauth_applies_canonical_transition(): assert transition_require_reauth(RunStatus.ANALYZING) is RunStatus.REAUTH_REQUIRED
def test_require_reauth_rejects_unrelated_status():
    try: transition_require_reauth(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
