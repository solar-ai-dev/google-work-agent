"""Canonical Run transition for require reauth."""

from google_work_agent.domain.run.guards.require_reauth import guard_require_reauth
from google_work_agent.domain.run.model import RunStatus


def transition_require_reauth(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_require_reauth(current_status)
    return RunStatus.REAUTH_REQUIRED
