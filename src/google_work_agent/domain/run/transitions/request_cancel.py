"""Canonical Run cancellation-request transition."""

from google_work_agent.domain.run.guards.request_cancel import guard_request_cancel
from google_work_agent.domain.run.model import RunStatus


def transition_request_cancel(current_status: RunStatus) -> RunStatus:
    guard_request_cancel(current_status)
    return RunStatus.CANCEL_REQUESTED
