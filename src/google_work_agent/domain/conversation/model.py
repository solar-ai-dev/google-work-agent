"""Conversation semantic invariants."""
from google_work_agent.domain.run.model import RunTransitionRejected

def guard_conversation_can_start_run(*, has_open_run: bool) -> None:
    """Conversation may contain many sequential Runs but at most one open Run."""
    if has_open_run:
        raise RunTransitionRejected("conversation already has an open Run")
