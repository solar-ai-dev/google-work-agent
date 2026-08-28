"""Read and persist a token-free connector connection projection."""

from collections.abc import Callable
from dataclasses import dataclass, replace

from google_work_agent.ports.connector.oauth_credential_port import (
    ConnectionMetadataV1,
    OAuthCredentialPort,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


@dataclass(frozen=True, slots=True)
class GetConnectionStatusQuery:
    connector_id: str


@dataclass(frozen=True, slots=True)
class GetConnectionStatusResult:
    connection: ConnectionMetadataV1


class GetConnectionStatusHandler:
    def __init__(
        self,
        credentials: OAuthCredentialPort,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork] | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._credentials = credentials
        self._unit_of_work_factory = unit_of_work_factory
        self._now_ms = now_ms

    def __call__(self, query: GetConnectionStatusQuery) -> GetConnectionStatusResult:
        connection = self._credentials.get_connection_status(query.connector_id)
        if (
            connection.connection_status == "CONNECTED"
            and connection.display_email is not None
            and self._unit_of_work_factory is not None
            and self._now_ms is not None
        ):
            with self._unit_of_work_factory() as unit_of_work:
                account = unit_of_work.connected_accounts.ensure_connected(
                    email=connection.display_email,
                    display_name=None,
                    connected_at_ms=self._now_ms(),
                )
                unit_of_work.commit()
            connection = replace(connection, account_id=account.account_id)
        return GetConnectionStatusResult(connection)


__all__ = ["GetConnectionStatusHandler", "GetConnectionStatusQuery", "GetConnectionStatusResult"]
