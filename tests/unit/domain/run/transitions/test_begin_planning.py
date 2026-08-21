from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_planning import transition_begin_planning

def test_begin_planning_applies_canonical_transition(): assert transition_begin_planning(RunStatus.ANALYZING) is RunStatus.PLANNING
def test_begin_planning_rejects_unrelated_status():
    try: transition_begin_planning(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
