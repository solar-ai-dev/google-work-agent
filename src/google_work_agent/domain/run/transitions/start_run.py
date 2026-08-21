"""Canonical transition for creating a new Run."""
from google_work_agent.domain.enums import RunStatus
from google_work_agent.domain.run.guards.start_run import guard_start_run

def transition_start_run(*, has_open_run: bool) -> RunStatus:
    guard_start_run(has_open_run=has_open_run)
    return RunStatus.CREATED
