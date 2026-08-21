"""Guard for request confirmation."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING})

def guard_request_confirmation(current_status: RunStatus) -> None:
    """Reject a request confirmation request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "request_confirmation")
