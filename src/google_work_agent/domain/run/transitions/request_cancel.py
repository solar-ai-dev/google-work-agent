"""Canonical Run cancellation-request transition."""

from google_work_agent.domain.run.guards.request_cancel import guard_request_cancel
from google_work_agent.domain.run.model import RunStatusV1


def transition_request_cancel(current_status: RunStatusV1) -> RunStatusV1:
    guard_request_cancel(current_status)
    return RunStatusV1.CANCEL_REQUESTED
