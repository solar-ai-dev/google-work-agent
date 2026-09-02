import pytest

from google_work_agent.domain.run.guards.request_confirmation import guard_request_confirmation
from google_work_agent.domain.run.model import RunStatusV1, RunTransitionRejected


def test_request_confirmation__distinguishes_pre_publish__and_review_reentry() -> None:
    guard_request_confirmation(RunStatusV1.ANALYZING)
    guard_request_confirmation(
        RunStatusV1.WAITING_APPROVAL,
        durable_review_disposition="CONFIRM",
    )
    with pytest.raises(RunTransitionRejected):
        guard_request_confirmation(RunStatusV1.WAITING_APPROVAL)
