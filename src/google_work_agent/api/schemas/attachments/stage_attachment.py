"""Stage-attachment wire request."""

from google_work_agent.api.schemas.model import ApiModel


class StageAttachmentRequest(ApiModel):
    """Base64-encoded JSON upload body."""

    filename: str
    mime_type: str
    data_base64: str
