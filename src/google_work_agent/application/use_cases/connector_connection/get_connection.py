"""Read connector connection status through the Application boundary."""

from dataclasses import dataclass
from typing import Any

from google_work_agent.application.ports.connector_failure import normalize_mcp_transport_failure
from google_work_agent.ports.mcp_transport import MCPTransportError


@dataclass(frozen=True, slots=True)
class GetConnectionQuery:
    connector_id: str = "google_workspace"


@dataclass(frozen=True, slots=True)
class GetConnectionResult:
    connection: Any


@dataclass(frozen=True, slots=True)
class GetConnectionHandler:
    service: Any

    def __call__(self, query: GetConnectionQuery) -> GetConnectionResult:
        if query.connector_id != "google_workspace":
            raise ValueError("unsupported connector")
        try:
            connection = self.service()
        except MCPTransportError as error:
            raise normalize_mcp_transport_failure(error) from error
        return GetConnectionResult(connection=connection)
