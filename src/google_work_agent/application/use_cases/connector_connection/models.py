"""Application projections for the current Google connection API."""

from dataclasses import dataclass
from enum import StrEnum

from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment


class CredentialState(StrEnum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED = "CONNECTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    KEYRING_UNAVAILABLE = "KEYRING_UNAVAILABLE"
    ERROR = "ERROR"


@dataclass(frozen=True, slots=True)
class OAuthStartResult:
    flow_id: str
    authorization_url: str
    callback_url: str
    expires_at_ms: int
    oauth_environment: OAuthEnvironment
    scopes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoogleConnectionStatus:
    connected: bool
    credential_state: CredentialState
    account_email: str | None
    display_name: str | None
    granted_scopes: tuple[str, ...]
    missing_scopes: tuple[str, ...]
    reauth_required: bool
    oauth_environment: OAuthEnvironment
    last_checked_at_ms: int
    safe_error_code: str | None = None
    safe_error_description: str | None = None


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    disconnected: bool
    credential_deleted: bool
    revoke_attempted: bool
    revoke_succeeded: bool
    credential_state: CredentialState


__all__ = [
    "CredentialState",
    "DisconnectResult",
    "GoogleConnectionStatus",
    "OAuthStartResult",
]
