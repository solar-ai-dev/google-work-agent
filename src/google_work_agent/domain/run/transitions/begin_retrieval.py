"""Canonical Run transition for begin retrieval."""

from google_work_agent.domain.run.guards.begin_retrieval import guard_begin_retrieval
from google_work_agent.domain.run.model import RunStatusV1


def transition_begin_retrieval(current_status: RunStatusV1) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_begin_retrieval(current_status)
    return RunStatusV1.RETRIEVING
