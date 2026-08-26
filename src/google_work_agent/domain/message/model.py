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


MAX_MESSAGE_UTF8_BYTES = 65_536


def validate_message_content(content: str) -> None:
    """Validate the persisted Message content boundary."""
    if len(content.encode("utf-8")) > MAX_MESSAGE_UTF8_BYTES:
        raise ValueError("message content exceeds 65536 UTF-8 bytes")
