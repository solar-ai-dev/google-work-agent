"""Application services for Gmail attachment READ and outbound staging."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports import (
    AttachmentDescriptor,
    AttachmentStagingPort,
    GmailAttachmentBytes,
    GmailAttachmentGateway,
)


@dataclass(frozen=True, slots=True)
class GetGmailAttachmentService:
    """Fetch one Gmail attachment's bytes for the download route to stream."""

    gateway: GmailAttachmentGateway

    def __call__(self, *, message_id: str, attachment_id: str) -> GmailAttachmentBytes:
        return self.gateway.get_gmail_attachment(message_id=message_id, attachment_id=attachment_id)


@dataclass(frozen=True, slots=True)
class StageAttachmentService:
    """Stage one outbound attachment's bytes and return its descriptor."""

    staging: AttachmentStagingPort

    def __call__(self, *, data: bytes, filename: str, mime_type: str) -> AttachmentDescriptor:
        return self.staging.stage(data=data, filename=filename, mime_type=mime_type)
