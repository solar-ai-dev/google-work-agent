"""Guard for complete answer only run."""

from google_work_agent.domain.run.model import RunStatus, RunTransitionRejected, require_status

_ALLOWED = frozenset({RunStatus.ANALYZING, RunStatus.RETRIEVING, RunStatus.PLANNING})


def guard_complete_answer_only_run(
    current_status: RunStatus,
    *,
    has_plan: bool,
    has_action: bool,
    has_open_write: bool,
    has_executing_read: bool,
    has_unresolved_recovery: bool,
) -> None:
    """Reject a complete answer only run request from an invalid Run status."""
    require_status(current_status, _ALLOWED, "complete_answer_only_run")
    if any(
        (
            has_plan,
            has_action,
            has_open_write,
            has_executing_read,
            has_unresolved_recovery,
        )
    ):
        raise RunTransitionRejected(
            "complete_answer_only_run requires no Plan, Action, open Write, "
            "executing READ, or unresolved Recovery"
        )
