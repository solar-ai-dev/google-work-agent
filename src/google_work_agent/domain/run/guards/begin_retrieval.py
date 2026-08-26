"""Canonical guard for entering a new Retrieval invocation."""

from google_work_agent.domain.run.model import RunStatus, require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.PLANNING})


def guard_begin_retrieval(current_status: RunStatus) -> None:
    """Reject a begin retrieval request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "begin_retrieval")
