"""Unit tests for Google connection identity provisioning wiring."""

from __future__ import annotations

from google_work_agent.application.google_connection import GetGoogleConnectionService
from google_work_agent.ports import CredentialState, GoogleConnectionStatus, OAuthEnvironment


class _FakeProvider:
    def __init__(self, status: GoogleConnectionStatus) -> None:
        self._status = status

    def start_oauth(self) -> object:
        raise NotImplementedError

    def get_connection_status(self) -> GoogleConnectionStatus:
        return self._status

    def disconnect(self) -> object:
        raise NotImplementedError


class _RecordingProvisioner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def ensure_google_account_connected(
        self, *, email: str, display_name: str | None, now_ms: int
    ) -> None:
        self.calls.append((email, display_name, now_ms))


def _status(*, connected: bool, account_email: str | None) -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        connected=connected,
        credential_state=CredentialState.CONNECTED if connected else CredentialState.NOT_CONNECTED,
        account_email=account_email,
        display_name="Display Name",
        granted_scopes=(),
        missing_scopes=(),
        reauth_required=False,
        oauth_environment=OAuthEnvironment.DEVELOPMENT,
        last_checked_at_ms=1_000,
    )


def test_provisions_account_when_connected_with_resolved_email() -> None:
    provisioner = _RecordingProvisioner()
    service = GetGoogleConnectionService(
        provider=_FakeProvider(_status(connected=True, account_email="user@example.com")),
        account_provisioner=provisioner,
        now_ms=lambda: 5_000,
    )

    status = service()

    assert status.connected is True
    assert provisioner.calls == [("user@example.com", "Display Name", 5_000)]


def test_does_not_provision_when_not_connected() -> None:
    provisioner = _RecordingProvisioner()
    service = GetGoogleConnectionService(
        provider=_FakeProvider(_status(connected=False, account_email=None)),
        account_provisioner=provisioner,
        now_ms=lambda: 5_000,
    )

    service()

    assert provisioner.calls == []


def test_does_not_provision_when_connected_but_email_unresolved() -> None:
    """A pre-fix (or pre-reconnect) session can be connected without the
    email scope having ever been granted; provisioning must not run on a
    guess and must not crash on the missing email."""

    provisioner = _RecordingProvisioner()
    service = GetGoogleConnectionService(
        provider=_FakeProvider(_status(connected=True, account_email=None)),
        account_provisioner=provisioner,
        now_ms=lambda: 5_000,
    )

    status = service()

    assert status.connected is True
    assert provisioner.calls == []


def test_works_without_a_provisioner_configured() -> None:
    service = GetGoogleConnectionService(
        provider=_FakeProvider(_status(connected=True, account_email="user@example.com"))
    )

    status = service()

    assert status.connected is True
