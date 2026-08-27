from __future__ import annotations

import pytest

from google_work_agent.application.google_connection import GetGoogleConnectionService
from google_work_agent.application.use_cases.connector_connection.get_connection import (
    GetConnectionHandler,
    GetConnectionQuery,
)
from google_work_agent.application.use_cases.connector_connection.models import (
    CredentialState,
    GoogleConnectionStatus,
)
from google_work_agent.ports.connector.mcp_client_port import (
    MCPClientPortError,
    MCPClientPortErrorCode,
)
from google_work_agent.ports.connector.oauth_credential_port import (
    ConnectionMetadataV1,
    OAuthEnvironment,
)
from google_work_agent.ports.connectors.failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)


def _status(
    *,
    connected: bool,
    email: str | None,
) -> GoogleConnectionStatus:
    return GoogleConnectionStatus(
        connected=connected,
        credential_state=(
            CredentialState.CONNECTED if connected else CredentialState.NOT_CONNECTED
        ),
        account_email=email,
        display_name="Display Name",
        granted_scopes=("scope-a",),
        missing_scopes=(),
        reauth_required=False,
        oauth_environment=OAuthEnvironment.DEVELOPMENT,
        last_checked_at_ms=1_000,
    )


class _ConnectionAccess:
    def __init__(
        self,
        status: GoogleConnectionStatus,
        *,
        can_provision: bool = True,
    ) -> None:
        self.status = status
        self.can_provision = can_provision
        self.provisioned: list[tuple[str, str | None, int]] = []
        self.clock_calls = 0

    def read_connection_status(self) -> GoogleConnectionStatus:
        return self.status

    def can_provision_connected_account(self) -> bool:
        return self.can_provision

    def current_time_ms(self) -> int:
        self.clock_calls += 1
        return 5_000

    def ensure_connected_account(
        self,
        *,
        email: str,
        display_name: str | None,
        now_ms: int,
    ) -> None:
        self.provisioned.append((email, display_name, now_ms))


def test_get_connection_handler_owns_connected_account_provisioning_and_time() -> None:
    access = _ConnectionAccess(_status(connected=True, email="user@example.com"))

    result = GetConnectionHandler(access)(GetConnectionQuery())

    assert result.connection.account_email == "user@example.com"
    assert access.clock_calls == 1
    assert access.provisioned == [("user@example.com", "Display Name", 5_000)]


@pytest.mark.parametrize(
    ("connected", "email", "can_provision"),
    [
        (False, None, True),
        (True, None, True),
        (True, "user@example.com", False),
    ],
)
def test_get_connection_handler_provisions_only_when_state_allows(
    connected: bool,
    email: str | None,
    can_provision: bool,
) -> None:
    access = _ConnectionAccess(
        _status(connected=connected, email=email),
        can_provision=can_provision,
    )

    GetConnectionHandler(access)(GetConnectionQuery())

    assert access.clock_calls == 0
    assert access.provisioned == []


class _FailingConnectionAccess(_ConnectionAccess):
    def read_connection_status(self) -> GoogleConnectionStatus:
        raise MCPClientPortError(
            code=MCPClientPortErrorCode.TIMEOUT,
            message="timeout",
        )


def test_get_connection_handler_normalizes_mcp_failure() -> None:
    access = _FailingConnectionAccess(_status(connected=False, email=None))

    with pytest.raises(ConnectorOperationFailure) as caught:
        GetConnectionHandler(access)(GetConnectionQuery())

    assert caught.value.code is ConnectorFailureCode.CONNECTION_UNAVAILABLE
    assert caught.value.detail_code == "MCP_TIMEOUT"
    assert caught.value.retryable is True


def test_get_connection_handler_rejects_unknown_connector_before_read() -> None:
    access = _ConnectionAccess(_status(connected=False, email=None))

    with pytest.raises(ConnectorOperationFailure) as caught:
        GetConnectionHandler(access)(GetConnectionQuery(connector_id="unsupported"))

    assert caught.value.code is ConnectorFailureCode.INVALID_ARGUMENT
    assert access.clock_calls == 0
    assert access.provisioned == []


class _Provider:
    def get_connection_status(self, connector_id: str) -> ConnectionMetadataV1:
        return ConnectionMetadataV1(
            schema_version=1,
            connector_id=connector_id,
            account_id="legacy@example.com",
            display_email="legacy@example.com",
            connection_status="CONNECTED",
            granted_scopes=("scope-a",),
            missing_required_scopes=(),
        )

    def start_oauth(self) -> object:
        raise AssertionError("not expected")

    def disconnect(self) -> object:
        raise AssertionError("not expected")


class _Provisioner:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str | None, int]] = []

    def ensure_google_account_connected(
        self,
        *,
        email: str,
        display_name: str | None,
        now_ms: int,
    ) -> None:
        self.calls.append((email, display_name, now_ms))


def test_legacy_get_connection_service_delegates_to_canonical_handler_semantics() -> None:
    provisioner = _Provisioner()
    service = GetGoogleConnectionService(
        provider=_Provider(),
        account_provisioner=provisioner,
        now_ms=lambda: 7_000,
    )

    result = service()

    assert result.account_email == "legacy@example.com"
    assert provisioner.calls == [("legacy@example.com", None, 7_000)]
