"""Canonical Run transition for request confirmation."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.request_confirmation import guard_request_confirmation

def transition_request_confirmation(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_request_confirmation(current_status)
    return RunStatus.WAITING_CONFIRMATION
