"""Get-attachment wire response."""

from google_work_agent.api.schemas.common import ApiModel


class AttachmentDescriptorResponse(ApiModel):
    staged_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    api_contract_version: str
