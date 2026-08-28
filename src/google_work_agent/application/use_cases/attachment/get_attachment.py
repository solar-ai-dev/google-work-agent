"""Fetch bounded Gmail attachment bytes through ConnectorReadPort."""

from base64 import urlsafe_b64decode
from dataclasses import dataclass
from typing import cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort


@dataclass(frozen=True, slots=True)
class GetAttachmentQuery:
    message_id: str
    attachment_id: str


@dataclass(frozen=True, slots=True)
class GetAttachmentResult:
    message_id: str
    attachment_id: str
    size_bytes: int
    sha256: str
    data: bytes


class GetAttachmentHandler:
    def __init__(
        self,
        *,
        connector_read: ConnectorReadPort,
        tool_registry: SignedToolRegistry,
        connector_id: str = "google_workspace",
    ) -> None:
        self._connector_read = connector_read
        self._tool_registry = tool_registry
        self._connector_id = connector_id

    def __call__(self, query: GetAttachmentQuery) -> GetAttachmentResult:
        binding = self._tool_registry.bind_required(
            self._connector_id, "gmail_get_attachment", "READ"
        )
        output = self._connector_read.execute_read(
            binding,
            {"message_id": query.message_id, "attachment_id": query.attachment_id},
        ).output
        encoded = str(output["data_base64url"])
        data = urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
        size_bytes = int(cast(str | int, output["size_bytes"]))
        if len(data) != size_bytes:
            raise ValueError("attachment size integrity check failed")
        return GetAttachmentResult(
            message_id=str(output["message_id"]),
            attachment_id=str(output["attachment_id"]),
            size_bytes=size_bytes,
            sha256=str(output["sha256"]),
            data=data,
        )


__all__ = ["GetAttachmentHandler", "GetAttachmentQuery", "GetAttachmentResult"]
