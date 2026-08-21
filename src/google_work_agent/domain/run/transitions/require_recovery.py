"""Canonical transition into RECOVERY_REQUIRED."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.require_recovery import guard_require_recovery

def transition_require_recovery(current_status: RunStatus) -> RunStatus:
    guard_require_recovery(current_status)
    return RunStatus.RECOVERY_REQUIRED
