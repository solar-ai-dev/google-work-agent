"""Canonical guard for starting Run analysis."""

from google_work_agent.domain.run.model import RunStatusV1, require_status

_ALLOWED = frozenset({RunStatusV1.CREATED})


def guard_start_analysis(current_status: RunStatusV1) -> None:
    """Reject a start analysis request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "start_analysis")
