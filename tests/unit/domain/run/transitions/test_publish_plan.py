from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import RunTransitionRejected
from google_work_agent.domain.run.transitions.publish_plan import transition_publish_plan

def test_publish_plan_applies_canonical_transition(): assert transition_publish_plan(RunStatus.PLANNING) is RunStatus.WAITING_APPROVAL
def test_publish_plan_rejects_unrelated_status():
    try: transition_publish_plan(RunStatus.FAILED)
    except RunTransitionRejected:return
    raise AssertionError("invalid transition was accepted")
