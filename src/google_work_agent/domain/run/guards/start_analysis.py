"""Guard for start analysis."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.CREATED})

def guard_start_analysis(current_status: RunStatus) -> None:
    """Reject a start analysis request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "start_analysis")
