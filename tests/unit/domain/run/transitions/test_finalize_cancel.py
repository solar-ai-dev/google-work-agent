from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.finalize_cancel import transition_finalize_cancel

def test_finalize_cancel_applies_canonical_transition(): assert transition_finalize_cancel(RunStatus.CANCEL_REQUESTED) is RunStatus.CANCELLED
def test_finalize_cancel_rejects_unrelated_status():
    try: transition_finalize_cancel(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
