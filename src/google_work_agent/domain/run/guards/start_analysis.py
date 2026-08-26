"""Canonical guard for starting Run analysis."""

from google_work_agent.domain.run.model import RunStatus, require_status

_ALLOWED = frozenset({RunStatus.CREATED})


def guard_start_analysis(current_status: RunStatus) -> None:
    """Reject a start analysis request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "start_analysis")
