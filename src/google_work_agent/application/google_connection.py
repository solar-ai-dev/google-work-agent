"""Legacy-compatible Google connection lifecycle collaborators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import parse_qs, urlparse

from google_work_agent.application.use_cases.connector_connection.get_connection import (
    GetConnectionHandler,
    GetConnectionQuery,
)
from google_work_agent.application.use_cases.connector_connection.models import (
    CredentialState,
    DisconnectResult,
    GoogleConnectionStatus,
    OAuthStartResult,
)
from google_work_agent.ports.connector.oauth_credential_port import (
    OAuthCredentialPort,
    OAuthEnvironment,
)


class GoogleAccountProvisioner(Protocol):
    def ensure_google_account_connected(
        self,
        *,
        email: str,
        display_name: str | None,
        now_ms: int,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StartGoogleOAuthService:
    provider: OAuthCredentialPort
    operation_ref_factory: Callable[[], str]
    now_ms: Callable[[], int]
    connector_id: str = "google_workspace"
    environment: OAuthEnvironment = OAuthEnvironment.DEVELOPMENT
    requested_scopes: tuple[str, ...] = ("openid",)

    def __call__(self) -> OAuthStartResult:
        started = self.provider.start_authorization(
            self.connector_id,
            self.environment,
            self.requested_scopes,
            self.operation_ref_factory(),
        )
        query = parse_qs(urlparse(started.authorization_url).query)
        callback_url = next(iter(query.get("redirect_uri", ())), "")
        scopes = tuple(next(iter(query.get("scope", ())), "").split())
        return OAuthStartResult(
            flow_id=started.callback_id,
            authorization_url=started.authorization_url,
            callback_url=callback_url,
            expires_at_ms=self.now_ms() + 300_000,
            oauth_environment=self.environment,
            scopes=scopes or self.requested_scopes,
        )


@dataclass(frozen=True, slots=True)
class GetGoogleConnectionService:
    """Compatibility façade over narrow access used by GetConnectionHandler."""

    provider: OAuthCredentialPort
    account_provisioner: GoogleAccountProvisioner | None = None
    now_ms: Callable[[], int] | None = None
    connector_id: str = "google_workspace"
    environment: OAuthEnvironment = OAuthEnvironment.DEVELOPMENT

    def read_connection_status(self) -> GoogleConnectionStatus:
        status = self.provider.get_connection_status(self.connector_id)
        credential_state = {
            "CONNECTED": CredentialState.CONNECTED,
            "REAUTH_REQUIRED": CredentialState.REAUTH_REQUIRED,
            "UNAVAILABLE": CredentialState.KEYRING_UNAVAILABLE,
        }.get(status.connection_status, CredentialState.NOT_CONNECTED)
        return GoogleConnectionStatus(
            connected=status.connection_status == "CONNECTED",
            credential_state=credential_state,
            account_email=status.display_email,
            display_name=None,
            granted_scopes=status.granted_scopes,
            missing_scopes=status.missing_required_scopes,
            reauth_required=status.connection_status == "REAUTH_REQUIRED",
            oauth_environment=self.environment,
            last_checked_at_ms=self.now_ms() if self.now_ms is not None else 0,
        )

    def can_provision_connected_account(self) -> bool:
        return self.account_provisioner is not None and self.now_ms is not None

    def current_time_ms(self) -> int:
        if self.now_ms is None:
            raise RuntimeError("connection provisioning clock is not configured")
        return self.now_ms()

    def ensure_connected_account(
        self,
        *,
        email: str,
        display_name: str | None,
        now_ms: int,
    ) -> None:
        if self.account_provisioner is None:
            raise RuntimeError("connection account provisioner is not configured")
        self.account_provisioner.ensure_google_account_connected(
            email=email,
            display_name=display_name,
            now_ms=now_ms,
        )

    def __call__(self) -> GoogleConnectionStatus:
        return GetConnectionHandler(self)(GetConnectionQuery()).connection


@dataclass(frozen=True, slots=True)
class DisconnectGoogleService:
    provider: OAuthCredentialPort
    operation_ref_factory: Callable[[], str]
    connector_id: str = "google_workspace"

    def __call__(self) -> DisconnectResult:
        status = self.provider.get_connection_status(self.connector_id)
        revoked = self.provider.revoke_connection(
            self.connector_id,
            status.account_id or status.display_email or "current",
            self.operation_ref_factory(),
        )
        disconnected = revoked.connection_status == "DISCONNECTED"
        return DisconnectResult(
            disconnected=disconnected,
            credential_deleted=revoked.local_credential_deleted,
            revoke_attempted=revoked.revocation_attempted,
            revoke_succeeded=revoked.revocation_attempted and disconnected,
            credential_state=(
                CredentialState.NOT_CONNECTED if disconnected else CredentialState.ERROR
            ),
        )
