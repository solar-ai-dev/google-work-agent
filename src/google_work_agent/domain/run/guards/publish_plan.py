"""Guard for publish plan."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.model import require_status

_ALLOWED = frozenset({RunStatus.PLANNING})

def guard_publish_plan(current_status: RunStatus) -> None:
    """Reject a publish plan request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "publish_plan")
