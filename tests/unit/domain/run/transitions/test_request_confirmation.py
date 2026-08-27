from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.request_confirmation import (
    transition_request_confirmation,
)


def test_request_confirmation_applies_canonical_transition():
    assert (
        transition_request_confirmation(RunStatusV1.ANALYZING) is RunStatusV1.WAITING_CONFIRMATION
    )


def test_request_confirmation_rejects_unrelated_status():
    try:
        transition_request_confirmation(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
