"""Google resource projection API schemas."""

from google_work_agent.api.schemas.common import ApiModel


class ResourceListResponse(ApiModel):
    source: str
    items: list[dict[str, object]]
    next_page_token: str | None
    api_contract_version: str


class GmailAttachmentMetadataResponse(ApiModel):
    message_id: str
    attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int | None


class GmailResourceDetailResponse(ApiModel):
    resource_id: str
    message_id: str
    sender_name: str | None
    sender_email: str | None
    recipients: list[str]
    cc: list[str]
    subject: str | None
    received_at: str | None
    body: str | None
    attachments: list[GmailAttachmentMetadataResponse]
    canonical_url: str
    api_contract_version: str
