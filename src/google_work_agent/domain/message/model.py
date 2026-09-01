"""Message domain model and semantic invariants."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Message:
    id: str
    conversation_id: str
    run_id: str | None
    role: str
    content: str
    created_at_ms: int
