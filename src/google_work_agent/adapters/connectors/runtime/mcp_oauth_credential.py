"""Google OAuth credential provider backed by MCP control calls."""

from __future__ import annotations

from google_work_agent.ports import (
    CredentialState,
    DisconnectResult,
    GoogleConnectionStatus,
    GoogleOAuthCredentialProvider,
    OAuthEnvironment,
    OAuthStartResult,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPort


class McpOAuthCredentialAdapter(GoogleOAuthCredentialProvider):
    def __init__(self, *, transport: MCPClientPort) -> None:
        self._transport = transport

    def start_oauth(self) -> OAuthStartResult:
        payload = self._transport.call_control(method="google.oauth.start", arguments={}).payload
        return OAuthStartResult(
            flow_id=str(payload["flow_id"]),
            authorization_url=str(payload["authorization_url"]),
            callback_url=str(payload["callback_url"]),
            expires_at_ms=int(payload["expires_at_ms"]),
            oauth_environment=OAuthEnvironment(str(payload["oauth_environment"])),
            scopes=tuple(str(item) for item in payload["scopes"]),
        )

    def get_connection_status(self) -> GoogleConnectionStatus:
        payload = self._transport.call_control(
            method="google.connection.get",
            arguments={},
        ).payload
        return GoogleConnectionStatus(
            connected=bool(payload["connected"]),
            credential_state=CredentialState(str(payload["credential_state"])),
            account_email=_optional_string(payload.get("account_email")),
            display_name=_optional_string(payload.get("display_name")),
            granted_scopes=tuple(str(item) for item in payload["granted_scopes"]),
            missing_scopes=tuple(str(item) for item in payload["missing_scopes"]),
            reauth_required=bool(payload["reauth_required"]),
            oauth_environment=OAuthEnvironment(str(payload["oauth_environment"])),
            last_checked_at_ms=int(payload["last_checked_at_ms"]),
            safe_error_code=_optional_string(payload.get("safe_error_code")),
            safe_error_description=_optional_string(payload.get("safe_error_description")),
        )

    def disconnect(self) -> DisconnectResult:
        payload = self._transport.call_control(
            method="google.connection.disconnect",
            arguments={},
        ).payload
        return DisconnectResult(
            disconnected=bool(payload["disconnected"]),
            credential_deleted=bool(payload["credential_deleted"]),
            revoke_attempted=bool(payload["revoke_attempted"]),
            revoke_succeeded=bool(payload["revoke_succeeded"]),
            credential_state=CredentialState(str(payload["credential_state"])),
        )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
