"""Canonical Run transition for complete write run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.complete_write_run import guard_complete_write_run

def transition_complete_write_run(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_complete_write_run(current_status)
    return RunStatus.COMPLETED
