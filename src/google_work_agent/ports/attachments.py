"""Gmail attachment READ and outbound staging port definitions."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, cast


class AttachmentStagingError(RuntimeError):
    """A sanitized staging failure whose code never contains file content."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class AttachmentDescriptor:
    """Minimal descriptor carried in outbound business arguments and claims."""

    staged_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str

    def to_json(self) -> dict[str, object]:
        return {
            "staged_attachment_id": self.staged_attachment_id,
            "filename": self.filename,
            "mime_type": self.mime_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
        }

    @classmethod
    def from_json(cls, payload: dict[str, object]) -> AttachmentDescriptor:
        try:
            return cls(
                staged_attachment_id=str(payload["staged_attachment_id"]),
                filename=str(payload["filename"]),
                mime_type=str(payload["mime_type"]),
                size_bytes=int(cast(int, payload["size_bytes"])),
                sha256=str(payload["sha256"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AttachmentStagingError("ATTACHMENT_DESCRIPTOR_MALFORMED") from error


class AttachmentStaging(Protocol):
    """Stage outbound attachment bytes behind a local storage boundary."""

    def stage(self, *, data: bytes, filename: str, mime_type: str) -> AttachmentDescriptor:
        """Persist bytes temporarily and return their integrity descriptor."""


class AttachmentDescriptorVerifier(Protocol):
    """Verify staged bytes without exposing them outside the staging adapter."""

    def verify_descriptor(self, descriptor: AttachmentDescriptor) -> None:
        """Fail when the descriptor no longer identifies the staged bytes."""


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
