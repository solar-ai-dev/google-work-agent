"""Get-Gmail-resource wire response."""

from typing import Literal

from google_work_agent.api.schemas.model import ApiModel


class GmailAttachmentMetadataResponse(ApiModel):
    schema_version: Literal[1]
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int | None


class GmailResourceDetailResponse(ApiModel):
    schema_version: Literal[1]
    resource_id: str
    message_id: str
    sender_name: str | None
    sender_email: str
    recipients: list[str]
    cc: list[str]
    subject: str
    received_at: str
    body: str
    attachments: list[GmailAttachmentMetadataResponse]
    canonical_url: str
