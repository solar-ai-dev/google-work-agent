from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.complete_write_run import transition_complete_write_run

def test_complete_write_run_applies_canonical_transition(): assert transition_complete_write_run(RunStatus.VERIFYING) is RunStatus.COMPLETED
def test_complete_write_run_rejects_unrelated_status():
    try: transition_complete_write_run(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
