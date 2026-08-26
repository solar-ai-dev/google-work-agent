"""Canonical transition for requiring Recovery."""

from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.recovery.guards.require_recovery import guard_require_recovery


def transition_require_recovery(current_status: RunStatus) -> RunStatus:
    """Suspend a non-terminal Run pending an explicit Recovery resolution."""
    guard_require_recovery(current_status)
    return RunStatus.RECOVERY_REQUIRED
