from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.begin_retrieval import transition_begin_retrieval


def test_begin_retrieval_applies_canonical_transition():
    assert transition_begin_retrieval(RunStatusV1.ANALYZING) is RunStatusV1.RETRIEVING


def test_begin_retrieval_rejects_unrelated_status():
    try:
        transition_begin_retrieval(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
