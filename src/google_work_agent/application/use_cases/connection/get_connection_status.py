"""Read and persist a token-free connector connection projection."""

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass, replace

from google_work_agent.ports.connector.connected_account_store import ConnectedAccountStore
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthConnectionMetadata,
    OAuthCredentialPort,
)


@dataclass(frozen=True, slots=True)
class GetConnectionStatusQuery:
    connector_id: str


@dataclass(frozen=True, slots=True)
class GetConnectionStatusResult:
    connection: OAuthConnectionMetadata


class GetConnectionStatusHandler:
    def __init__(
        self,
        credentials: OAuthCredentialPort,
        *,
        connected_account_store_factory: (
            Callable[[], AbstractContextManager[ConnectedAccountStore]] | None
        ) = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self._credentials = credentials
        self._connected_account_store_factory = connected_account_store_factory
        self._now_ms = now_ms

    def __call__(self, query: GetConnectionStatusQuery) -> GetConnectionStatusResult:
        connection = self._credentials.get_connection_status(query.connector_id)
        if (
            connection.connection_status == "CONNECTED"
            and connection.display_email is not None
            and connection.account_id is not None
            and self._connected_account_store_factory is not None
            and self._now_ms is not None
        ):
            with self._connected_account_store_factory() as store:
                account = store.ensure_connected(
                    account_id=connection.account_id,
                    email=connection.display_email,
                    display_name=None,
                    connected_at_ms=self._now_ms(),
                )
            connection = replace(connection, account_id=account.account_id)
        return GetConnectionStatusResult(connection)


__all__ = ["GetConnectionStatusHandler", "GetConnectionStatusQuery", "GetConnectionStatusResult"]
