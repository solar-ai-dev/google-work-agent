"""Connector-parameterized OAuth credential boundary."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from google_work_agent.ports.system.contracts.operational_command_replay import (
    OperationalReconcileResultV1,
)

type AccessContextHandle = str


class OAuthEnvironment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


@dataclass(frozen=True, slots=True)
class OAuthAuthorizationStart:
    schema_version: Literal[1]
    authorization_url: str
    callback_id: str


@dataclass(frozen=True, slots=True)
class OAuthConnectionMetadata:
    schema_version: Literal[1]
    connector_id: str
    account_id: str | None
    display_email: str | None
    connection_status: Literal[
        "CONNECTING", "CONNECTED", "DISCONNECTED", "REAUTH_REQUIRED", "UNAVAILABLE"
    ]
    granted_scopes: tuple[str, ...]
    missing_required_scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class OAuthRevokeResult:
    schema_version: Literal[1]
    revocation_attempted: bool
    local_credential_deleted: bool
    connection_status: Literal["DISCONNECTED", "UNAVAILABLE"]


class OAuthCredentialPort(Protocol):
    def start_authorization(
        self,
        connector_id: str,
        environment: OAuthEnvironment,
        requested_scopes: tuple[str, ...],
        operation_ref: str,
    ) -> OAuthAuthorizationStart: ...

    def reconcile_authorization_start(
        self, connector_id: str, operation_ref: str
    ) -> OperationalReconcileResultV1: ...

    def refresh_access(self, connector_id: str, account_id: str) -> AccessContextHandle: ...

    def get_connection_status(self, connector_id: str) -> OAuthConnectionMetadata: ...

    def revoke_connection(
        self, connector_id: str, account_id: str, operation_ref: str
    ) -> OAuthRevokeResult: ...

    def reconcile_revoke_connection(
        self, connector_id: str, account_id: str, operation_ref: str
    ) -> OperationalReconcileResultV1: ...


__all__ = [
    "AccessContextHandle",
    "OAuthAuthorizationStart",
    "OAuthConnectionMetadata",
    "OAuthCredentialPort",
    "OAuthEnvironment",
    "OAuthRevokeResult",
]
