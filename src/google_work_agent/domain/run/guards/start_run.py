"""Guard for starting a new Run in a Conversation."""

from google_work_agent.domain.run.model import RunTransitionRejected


def guard_start_run(*, has_open_run: bool) -> None:
    """Enforce the one-open-Run-per-Conversation invariant."""
    if has_open_run:
        raise RunTransitionRejected("start_run requires the conversation to have no open Run")
