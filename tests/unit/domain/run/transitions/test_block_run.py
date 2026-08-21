from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.block_run import transition_block_run

def test_block_run_applies_canonical_transition(): assert transition_block_run(RunStatus.CREATED) is RunStatus.BLOCKED
def test_block_run_rejects_unrelated_status():
    try: transition_block_run(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
