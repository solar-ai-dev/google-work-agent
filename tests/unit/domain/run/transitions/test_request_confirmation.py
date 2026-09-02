from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected
from google_work_agent.domain.run.transitions.request_confirmation import (
    transition_request_confirmation,
)


def test_request_confirmation__applies_canonical__transition() -> None:
    assert (
        transition_request_confirmation(RunStatusV1.ANALYZING) is RunStatusV1.WAITING_CONFIRMATION
    )


def test_request_confirmation__rejects_unrelated__status() -> None:
    try:
        transition_request_confirmation(RunStatusV1.FAILED)
    except RunTransitionRejected:
        return
    raise AssertionError("invalid transition was accepted")
