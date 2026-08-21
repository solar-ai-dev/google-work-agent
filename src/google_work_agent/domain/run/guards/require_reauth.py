"""Guard for require reauth."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING, RunStatus.WAITING_APPROVAL, RunStatus.EXECUTING, RunStatus.VERIFYING, RunStatus.RECOVERY_REQUIRED})

def guard_require_reauth(current_status: RunStatus) -> None:
    """Reject a require reauth request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "require_reauth")
