"""Application services for Google connection lifecycle."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from google_work_agent.ports import (
    DisconnectResult,
    GoogleConnectionStatus,
    GoogleOAuthCredentialProvider,
    OAuthStartResult,
)


@dataclass(frozen=True, slots=True)
class StartGoogleOAuthService:
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> OAuthStartResult:
        return self.provider.start_oauth()


@dataclass(frozen=True, slots=True)
class GetGoogleConnectionService:
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> GoogleConnectionStatus:
        return self.provider.get_connection_status()


@dataclass(frozen=True, slots=True)
class DisconnectGoogleService:
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> DisconnectResult:
        return self.provider.disconnect()


def connection_status_payload(status: GoogleConnectionStatus) -> dict[str, object]:
    return asdict(status)
