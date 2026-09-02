from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.start_analysis import transition_start_analysis


def test_start_analysis__applies_canonical__transition() -> None:
    assert transition_start_analysis(RunStatusV1.CREATED) is RunStatusV1.ANALYZING


def test_start_analysis__rejects_unrelated__status() -> None:
    try:
        transition_start_analysis(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
