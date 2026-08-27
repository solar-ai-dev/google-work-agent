"""Connector-neutral authorized WRITE boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from google_work_agent.ports.connector.connector_read_port import JsonValue
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1


@dataclass(frozen=True, slots=True)
class ConnectorWriteResultV1:
    schema_version: Literal[1]
    success: bool
    delivery_certainty: Literal["NOT_SENT", "MAY_HAVE_BEEN_SENT", "SENT_RESPONSE_LOST"] | None
    provider_request_id: str | None
    response_metadata: dict[str, str | int | float | bool | None] | None
    error_code: str | None


class ConnectorWritePort(Protocol):
    def execute_write(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
        claim_token: dict[str, JsonValue],
    ) -> ConnectorWriteResultV1: ...


__all__ = ["ConnectorWritePort", "ConnectorWriteResultV1"]
