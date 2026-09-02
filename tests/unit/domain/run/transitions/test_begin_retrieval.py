from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_retrieval import transition_begin_retrieval


def test_begin_retrieval__applies_canonical__transition() -> None:
    assert transition_begin_retrieval(RunStatusV1.ANALYZING) is RunStatusV1.RETRIEVING


def test_begin_retrieval__rejects_unrelated__status() -> None:
    try:
        transition_begin_retrieval(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
