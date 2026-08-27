"""Canonical Run transition for complete answer only run."""

from google_work_agent.domain.run.guards.complete_answer_only_run import (
    guard_complete_answer_only_run,
)
from google_work_agent.domain.run.model import RunStatusV1


def transition_complete_answer_only_run(
    current_status: RunStatusV1,
    *,
    has_plan: bool = False,
    has_action: bool = False,
    has_open_write: bool = False,
    has_executing_read: bool = False,
    has_unresolved_recovery: bool = False,
) -> RunStatusV1:
    """Return the next Run status after enforcing the canonical guard."""
    guard_complete_answer_only_run(
        current_status,
        has_plan=has_plan,
        has_action=has_action,
        has_open_write=has_open_write,
        has_executing_read=has_executing_read,
        has_unresolved_recovery=has_unresolved_recovery,
    )
    return RunStatusV1.COMPLETED
