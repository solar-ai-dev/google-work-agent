"""Read connector connection status through the canonical Application boundary."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.ports.connectors.failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
    normalize_mcp_transport_failure,
)
from google_work_agent.ports import GoogleConnectionStatus
from google_work_agent.ports.connector.mcp_client_port import MCPClientPortError


class GetConnectionAccess(Protocol):
    def read_connection_status(self) -> GoogleConnectionStatus: ...

    def can_provision_connected_account(self) -> bool: ...

    def current_time_ms(self) -> int: ...

    def ensure_connected_account(
        self,
        *,
        email: str,
        display_name: str | None,
        now_ms: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class GetConnectionQuery:
    connector_id: str = "google_workspace"


@dataclass(frozen=True, slots=True)
class GetConnectionResult:
    connection: GoogleConnectionStatus


@dataclass(frozen=True, slots=True)
class GetConnectionHandler:
    access: GetConnectionAccess

    def __call__(self, query: GetConnectionQuery) -> GetConnectionResult:
        if query.connector_id != "google_workspace":
            raise ConnectorOperationFailure(
                code=ConnectorFailureCode.INVALID_ARGUMENT,
                detail_code="CONNECTOR_NOT_SUPPORTED",
            )
        try:
            connection = self.access.read_connection_status()
        except MCPClientPortError as error:
            raise normalize_mcp_transport_failure(error) from error

        if (
            connection.connected
            and connection.account_email is not None
            and self.access.can_provision_connected_account()
        ):
            self.access.ensure_connected_account(
                email=connection.account_email,
                display_name=connection.display_name,
                now_ms=self.access.current_time_ms(),
            )
        return GetConnectionResult(connection=connection)
