"""Canonical guard for entering a new Retrieval invocation."""

from google_work_agent.domain.run.model import RunStatusV1, require_status

_ALLOWED = frozenset({RunStatusV1.ANALYZING, RunStatusV1.PLANNING})


def guard_begin_retrieval(current_status: RunStatusV1) -> None:
    """Reject a begin retrieval request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "begin_retrieval")
