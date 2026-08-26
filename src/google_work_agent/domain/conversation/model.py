"""Conversation domain model and semantic invariants."""

from dataclasses import dataclass

from google_work_agent.domain.run.model import RunTransitionRejected


@dataclass(frozen=True, slots=True)
class Conversation:
    id: str
    account_id: str
    title: str
    created_at_ms: int
    updated_at_ms: int


def guard_conversation_can_start_run(*, has_open_run: bool) -> None:
    """Conversation may contain many sequential Runs but at most one open Run."""
    if has_open_run:
        raise RunTransitionRejected("conversation already has an open Run")
