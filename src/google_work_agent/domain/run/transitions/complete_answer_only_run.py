"""Canonical Run transition for complete answer only run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.complete_answer_only_run import guard_complete_answer_only_run

def transition_complete_answer_only_run(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_complete_answer_only_run(current_status)
    return RunStatus.COMPLETED
