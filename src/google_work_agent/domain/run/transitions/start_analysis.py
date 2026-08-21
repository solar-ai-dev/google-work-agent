"""Canonical Run transition for start analysis."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.start_analysis import guard_start_analysis

def transition_start_analysis(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_start_analysis(current_status)
    return RunStatus.ANALYZING
