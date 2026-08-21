"""Canonical Run transition for publish plan."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.publish_plan import guard_publish_plan

def transition_publish_plan(current_status: RunStatus) -> RunStatus:
    """Return the next Run status after enforcing the canonical guard."""
    guard_publish_plan(current_status)
    return RunStatus.WAITING_APPROVAL
