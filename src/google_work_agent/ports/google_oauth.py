"""Google OAuth credential provider contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OAuthEnvironment(StrEnum):
    DEVELOPMENT = "DEVELOPMENT"
    STAGING = "STAGING"
    PRODUCTION = "PRODUCTION"


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


@dataclass(frozen=True, slots=True)
class DisconnectResult:
    disconnected: bool
    credential_deleted: bool
    revoke_attempted: bool
    revoke_succeeded: bool
    credential_state: CredentialState


class GoogleOAuthCredentialProvider(Protocol):
    """Own the desktop OAuth flow and secret lifecycle."""

    def start_oauth(self) -> OAuthStartResult:
        """Start one desktop OAuth flow and return browser metadata."""

    def get_connection_status(self) -> GoogleConnectionStatus:
        """Return sanitized Google connection metadata."""

    def disconnect(self) -> DisconnectResult:
        """Disconnect the current Google account and clear credentials."""
