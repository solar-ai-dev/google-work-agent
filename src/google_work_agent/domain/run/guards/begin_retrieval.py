"""Guard for begin retrieval."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.PLANNING})

def guard_begin_retrieval(current_status: RunStatus) -> None:
    """Reject a begin retrieval request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "begin_retrieval")
