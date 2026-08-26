from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_retrieval import transition_begin_retrieval


def test_begin_retrieval_applies_canonical_transition():
    assert transition_begin_retrieval(RunStatus.ANALYZING) is RunStatus.RETRIEVING


def test_begin_retrieval_rejects_unrelated_status():
    try:
        transition_begin_retrieval(RunStatus.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
