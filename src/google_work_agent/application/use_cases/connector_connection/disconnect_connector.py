"""Disconnect a connector through the canonical Application boundary."""

from dataclasses import dataclass
from typing import Any

from google_work_agent.application.ports.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_mcp_transport_failure,
)
from google_work_agent.ports.mcp_transport import MCPTransportError


@dataclass(frozen=True, slots=True)
class DisconnectConnectorCommand:
    connector_id: str = "google_workspace"


@dataclass(frozen=True, slots=True)
class DisconnectConnectorResult:
    disconnect: Any


@dataclass(frozen=True, slots=True)
class DisconnectConnectorHandler:
    service: Any

    def __call__(self, command: DisconnectConnectorCommand) -> DisconnectConnectorResult:
        if command.connector_id != "google_workspace":
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.INVALID_ARGUMENT,
                detail_code="CONNECTOR_NOT_SUPPORTED",
            )
        try:
            disconnect = self.service()
        except MCPTransportError as error:
            raise normalize_mcp_transport_failure(error) from error
        return DisconnectConnectorResult(disconnect=disconnect)
