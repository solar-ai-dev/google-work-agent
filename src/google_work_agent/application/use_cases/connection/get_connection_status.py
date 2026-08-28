"""Read a token-free connector connection projection."""

from dataclasses import dataclass

from google_work_agent.ports.connector.oauth_credential_port import (
    ConnectionMetadataV1,
    OAuthCredentialPort,
)


@dataclass(frozen=True, slots=True)
class GetConnectionStatusQuery:
    connector_id: str


@dataclass(frozen=True, slots=True)
class GetConnectionStatusResult:
    connection: ConnectionMetadataV1


class GetConnectionStatusHandler:
    def __init__(self, credentials: OAuthCredentialPort) -> None:
        self._credentials = credentials

    def __call__(self, query: GetConnectionStatusQuery) -> GetConnectionStatusResult:
        return GetConnectionStatusResult(
            self._credentials.get_connection_status(query.connector_id)
        )


__all__ = ["GetConnectionStatusHandler", "GetConnectionStatusQuery", "GetConnectionStatusResult"]
