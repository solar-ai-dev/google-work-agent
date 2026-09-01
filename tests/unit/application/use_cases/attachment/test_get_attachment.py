"""Exact ownership smoke gate for the canonical Application module."""

from base64 import urlsafe_b64encode
from hashlib import sha256

import pytest

from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.attachment.get_attachment import (
    GetAttachmentHandler,
    GetAttachmentQuery,
)
from google_work_agent.ports.connector.connector_failure import ConnectorOperationFailure
from google_work_agent.ports.connector.connector_read_port import ConnectorReadResultV1, JsonValue
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)


class _AttachmentRead:
    def __init__(self, *, message_id: str = "message-1") -> None:
        self.message_id = message_id

    def execute_read(
        self,
        _binding: ValidatedConnectorToolBindingV1,
        _tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        data = b"attachment"
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id="gmail_get_attachment",
            request_id="read-1",
            output={
                "message_id": self.message_id,
                "attachment_id": "attachment-1",
                "size_bytes": len(data),
                "sha256": sha256(data).hexdigest(),
                "data_base64url": urlsafe_b64encode(data).rstrip(b"=").decode("ascii"),
            },
            next_page_token=None,
            total_count=None,
        )


def test_get_attachment_verifies_identity_size_and_hash() -> None:
    result = GetAttachmentHandler(
        connector_read=_AttachmentRead(),
        tool_registry=load_signed_tool_registry(),
    )(GetAttachmentQuery("message-1", "attachment-1"))

    assert result.data == b"attachment"
    assert result.size_bytes == len(result.data)


def test_get_attachment_rejects_mismatched_connector_identity() -> None:
    handler = GetAttachmentHandler(
        connector_read=_AttachmentRead(message_id="other-message"),
        tool_registry=load_signed_tool_registry(),
    )

    with pytest.raises(ConnectorOperationFailure) as caught:
        handler(GetAttachmentQuery("message-1", "attachment-1"))

    assert caught.value.detail_code == "ATTACHMENT_RESPONSE_INVALID"
