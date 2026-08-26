"""Canonical Run transition for finalize cancel."""

from google_work_agent.domain.run.guards.finalize_cancel import guard_finalize_cancel
from google_work_agent.domain.run.model import RunStatus


def transition_finalize_cancel(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_finalize_cancel(current_status)
    return RunStatus.CANCELLED
