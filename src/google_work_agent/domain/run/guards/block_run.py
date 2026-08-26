"""Guard for block run."""

from google_work_agent.domain.run.model import RunStatus, require_status

_ALLOWED = frozenset(
    {
        RunStatus.CREATED,
        RunStatus.ANALYZING,
        RunStatus.RETRIEVING,
        RunStatus.WAITING_CONFIRMATION,
        RunStatus.PLANNING,
        RunStatus.WAITING_APPROVAL,
    }
)


def guard_block_run(current_status: RunStatus) -> None:
    """Reject a block run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "block_run")
