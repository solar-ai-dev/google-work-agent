"""Guard for requesting Run cancellation."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import TERMINAL_RUN_STATUSES, RunTransitionRejected

def guard_request_cancel(current_status: RunStatus) -> None:
    if current_status in TERMINAL_RUN_STATUSES:
        raise RunTransitionRejected(f"request_cancel rejects terminal status {current_status.value}")
