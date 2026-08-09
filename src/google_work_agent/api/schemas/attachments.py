"""Gmail attachment staging API schemas."""

from google_work_agent.api.schemas.common import ApiModel


class StageAttachmentRequest(ApiModel):
    """Base64-encoded upload body.

    The mutation endpoints in this API only ever accept
    ``Content-Type: application/json`` (see access_guard's CSRF content-type
    check), so this stays a JSON body rather than a multipart upload.
    """

    filename: str
    mime_type: str
    data_base64: str


class AttachmentDescriptorResponse(ApiModel):
    staged_attachment_id: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    api_contract_version: str
