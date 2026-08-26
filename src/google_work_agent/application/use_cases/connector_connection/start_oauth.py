"""Start connector OAuth through the Application boundary."""

from dataclasses import dataclass
from typing import Any

from google_work_agent.ports.connectors.failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_mcp_transport_failure,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPortError


@dataclass(frozen=True, slots=True)
class StartOAuthCommand:
    connector_id: str = "google_workspace"


@dataclass(frozen=True, slots=True)
class StartOAuthResult:
    oauth: Any


@dataclass(frozen=True, slots=True)
class StartOAuthHandler:
    service: Any

    def __call__(self, command: StartOAuthCommand) -> StartOAuthResult:
        if command.connector_id != "google_workspace":
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.INVALID_ARGUMENT,
                detail_code="CONNECTOR_NOT_SUPPORTED",
            )
        try:
            oauth = self.service()
        except MCPClientPortError as error:
            raise normalize_mcp_transport_failure(error) from error
        return StartOAuthResult(oauth=oauth)
