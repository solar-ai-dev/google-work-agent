"""Canonical Run transition for begin retrieval."""

from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.begin_retrieval import guard_begin_retrieval


def transition_begin_retrieval(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_begin_retrieval(current_status)
    return RunStatus.RETRIEVING
