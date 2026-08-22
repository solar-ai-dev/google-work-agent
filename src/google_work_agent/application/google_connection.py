"""Legacy-compatible Google connection lifecycle collaborators."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Protocol

from google_work_agent.application.use_cases.connector_connection.get_connection import (
    GetConnectionHandler,
    GetConnectionQuery,
)
from google_work_agent.ports import (
    DisconnectResult,
    GoogleConnectionStatus,
    GoogleOAuthCredentialProvider,
    OAuthStartResult,
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
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> OAuthStartResult:
        return self.provider.start_oauth()


@dataclass(frozen=True, slots=True)
class GetGoogleConnectionService:
    """Compatibility façade over narrow access used by GetConnectionHandler."""

    provider: GoogleOAuthCredentialProvider
    account_provisioner: GoogleAccountProvisioner | None = None
    now_ms: Callable[[], int] | None = None

    def read_connection_status(self) -> GoogleConnectionStatus:
        return self.provider.get_connection_status()

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
    provider: GoogleOAuthCredentialProvider

    def __call__(self) -> DisconnectResult:
        return self.provider.disconnect()


def connection_status_payload(status: GoogleConnectionStatus) -> dict[str, object]:
    return asdict(status)
