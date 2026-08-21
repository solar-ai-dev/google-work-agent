"""Guard for complete answer only run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING})

def guard_complete_answer_only_run(current_status: RunStatus) -> None:
    """Reject a complete answer only run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "complete_answer_only_run")
