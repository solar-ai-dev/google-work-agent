"""Gmail attachment READ gateway port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class GmailAttachmentBytes:
    """One Gmail attachment's bytes plus the metadata needed to stream it.

    Instances of this type must never be persisted, logged, or handed to an
    LLM/agent -- only the FastAPI download route consumes ``data``, and only
    to stream it straight back to the browser.
    """

    message_id: str
    attachment_id: str
    size_bytes: int
    sha256: str
    data: bytes


class GmailAttachmentGateway(Protocol):
    """Read-only gateway over one Gmail message's attachment bytes."""

    def get_gmail_attachment(self, *, message_id: str, attachment_id: str) -> GmailAttachmentBytes:
        """Return one Gmail attachment's bytes."""
