"""Guard for begin planning."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING})

def guard_begin_planning(current_status: RunStatus) -> None:
    """Reject a begin planning request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "begin_planning")
