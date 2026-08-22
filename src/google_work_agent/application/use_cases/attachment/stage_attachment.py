"""Stage outbound attachment bytes through the Application boundary."""

from dataclasses import dataclass
from typing import Any

from google_work_agent.ports.connectors.failure import (
    normalize_attachment_staging_failure,
)
from google_work_agent.ports import AttachmentStagingError


@dataclass(frozen=True, slots=True)
class StageAttachmentCommand:
    data: bytes
    filename: str
    mime_type: str


@dataclass(frozen=True, slots=True)
class StageAttachmentResult:
    descriptor: Any


@dataclass(frozen=True, slots=True)
class StageAttachmentHandler:
    service: Any

    def __call__(self, command: StageAttachmentCommand) -> StageAttachmentResult:
        try:
            descriptor = self.service(
                data=command.data,
                filename=command.filename,
                mime_type=command.mime_type,
            )
        except AttachmentStagingError as error:
            raise normalize_attachment_staging_failure(error) from error
        return StageAttachmentResult(descriptor=descriptor)
