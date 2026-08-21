"""Guard for complete write run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.VERIFYING})

def guard_complete_write_run(current_status: RunStatus) -> None:
    """Reject a complete write run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "complete_write_run")
