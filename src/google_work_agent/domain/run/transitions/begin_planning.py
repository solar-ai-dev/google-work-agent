"""Canonical Run transition for begin planning."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.begin_planning import guard_begin_planning

def transition_begin_planning(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_begin_planning(current_status)
    return RunStatus.PLANNING
