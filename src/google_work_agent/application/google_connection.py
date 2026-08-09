"""Application services for Google connection lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from google_work_agent.ports import (
    DisconnectResult,
    GoogleConnectionStatus,
    GoogleOAuthCredentialProvider,
    OAuthStartResult,
)


class GoogleAccountProvisioner(Protocol):
    """Identity-record side of an observed Google connection.

    Kept as a narrow Protocol so GetGoogleConnectionService does not need to
    know about SQLite or the `google_accounts` table directly.
    """

    def ensure_google_account_connected(
        self, *, email: str, display_name: str | None, now_ms: int
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class StartGoogleOAuthService:
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> OAuthStartResult:
        return self.provider.start_oauth()


@dataclass(frozen=True, slots=True)
class GetGoogleConnectionService:
    provider: GoogleOAuthCredentialProvider
    account_provisioner: GoogleAccountProvisioner | None = None
    now_ms: Callable[[], int] | None = None

    def __call__(self) -> GoogleConnectionStatus:
        status = self.provider.get_connection_status()
        if (
            self.account_provisioner is not None
            and self.now_ms is not None
            and status.connected
            and status.account_email is not None
        ):
            self.account_provisioner.ensure_google_account_connected(
                email=status.account_email,
                display_name=status.display_name,
                now_ms=self.now_ms(),
            )
        return status


@dataclass(frozen=True, slots=True)
class DisconnectGoogleService:
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> DisconnectResult:
        return self.provider.disconnect()


def connection_status_payload(status: GoogleConnectionStatus) -> dict[str, object]:
    return asdict(status)
