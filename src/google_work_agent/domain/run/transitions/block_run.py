"""Canonical Run transition for block run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.block_run import guard_block_run

def transition_block_run(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_block_run(current_status)
    return RunStatus.BLOCKED
