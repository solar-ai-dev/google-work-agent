from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.start_analysis import transition_start_analysis


def test_start_analysis_applies_canonical_transition():
    assert transition_start_analysis(RunStatus.CREATED) is RunStatus.ANALYZING


def test_start_analysis_rejects_unrelated_status():
    try:
        transition_start_analysis(RunStatus.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
