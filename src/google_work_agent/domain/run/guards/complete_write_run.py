"""Guard for complete write run."""

from google_work_agent.domain.run.model import RunStatus, require_status

_ALLOWED = frozenset({RunStatus.WAITING_APPROVAL, RunStatus.VERIFYING})


def guard_complete_write_run(current_status: RunStatus) -> None:
    """Reject a complete write run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "complete_write_run")
