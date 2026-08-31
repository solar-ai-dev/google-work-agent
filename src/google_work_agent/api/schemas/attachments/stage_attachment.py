"""Stage-attachment multipart command metadata."""

from pydantic import Field

from google_work_agent.api.schemas.model import ApiModel


class StageAttachmentRequest(ApiModel):
    """Typed non-file fields of the canonical multipart request."""

    command_id: str = Field(min_length=1, max_length=128)
