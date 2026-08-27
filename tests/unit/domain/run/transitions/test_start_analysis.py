from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.start_analysis import transition_start_analysis


def test_start_analysis_applies_canonical_transition():
    assert transition_start_analysis(RunStatusV1.CREATED) is RunStatusV1.ANALYZING


def test_start_analysis_rejects_unrelated_status():
    try:
        transition_start_analysis(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
