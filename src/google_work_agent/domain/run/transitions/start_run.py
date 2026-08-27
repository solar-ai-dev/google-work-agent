"""Canonical transition for creating a new Run."""

from google_work_agent.domain.run.guards.start_run import guard_start_run
from google_work_agent.domain.run.model import RunStatusV1


def transition_start_run(*, has_open_run: bool) -> RunStatusV1:
    guard_start_run(has_open_run=has_open_run)
    return RunStatusV1.CREATED
