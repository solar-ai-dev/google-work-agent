"""Guard for finalize cancel."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.CANCEL_REQUESTED, RunStatus.VERIFYING, RunStatus.REAUTH_REQUIRED})

def guard_finalize_cancel(current_status: RunStatus) -> None:
    """Reject a finalize cancel request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "finalize_cancel")
