"""Application services for Gmail attachment READ and outbound staging."""

from __future__ import annotations

from base64 import urlsafe_b64decode
from dataclasses import dataclass
from hashlib import sha256

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort
from google_work_agent.ports.system.attachment_staging_port import (
    AttachmentStagingPort,
    StagedAttachmentDescriptorV1,
)


@dataclass(frozen=True, slots=True)
class GmailAttachmentBytes:
    message_id: str
    attachment_id: str
    size_bytes: int
    sha256: str
    data: bytes


@dataclass(frozen=True, slots=True)
class GetGmailAttachmentService:
    connector_reader: ConnectorReadPort
    tool_registry: SignedToolRegistry
    connector_id: str = "google_workspace"

    def __call__(self, *, message_id: str, attachment_id: str) -> GmailAttachmentBytes:
        binding = self.tool_registry.bind_required(
            self.connector_id,
            "gmail_get_attachment",
            "READ",
        )
        result = self.connector_reader.execute_read(
            binding,
            {"message_id": message_id, "attachment_id": attachment_id},
        )
        output = result.output
        encoded = str(output["data_base64url"])
        padding = "=" * (-len(encoded) % 4)
        return GmailAttachmentBytes(
            message_id=str(output["message_id"]),
            attachment_id=str(output["attachment_id"]),
            size_bytes=int(output["size_bytes"]),
            sha256=str(output["sha256"]),
            data=urlsafe_b64decode(encoded + padding),
        )


@dataclass(frozen=True, slots=True)
class StageAttachmentService:
    staging: AttachmentStagingPort

    def __call__(
        self, *, data: bytes, filename: str, mime_type: str
    ) -> StagedAttachmentDescriptorV1:
        operation_ref = sha256(
            filename.encode("utf-8") + b"\0" + mime_type.encode("utf-8") + b"\0" + data
        ).hexdigest()
        return self.staging.stage(operation_ref, data, filename, mime_type)


__all__ = ["GetGmailAttachmentService", "GmailAttachmentBytes", "StageAttachmentService"]
