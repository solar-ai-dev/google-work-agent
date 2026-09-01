from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.mcp_oauth_credential import (
    McpOAuthCredentialAdapter,
)
from google_work_agent.ports.connector.mcp_client_port import MCPToolCallResultV1


class _RuntimeHandle:
    pass


class _Client:
    def call_tool(
        self,
        connector_id: str,
        tool_id: str,
        arguments: object,
        timeout_ms: int,
    ) -> MCPToolCallResultV1:
        assert connector_id == "google_workspace"
        assert tool_id == "google.connection.get"
        assert arguments == {}
        assert timeout_ms == 30_000
        return MCPToolCallResultV1(
            schema_version=1,
            tool_id=tool_id,
            transport_status="OK",
            payload={
                "connected": True,
                "credential_state": "CONNECTED",
                "account_id": "google-subject",
                "account_email": "user@example.com",
                "granted_scopes": ["openid"],
                "missing_scopes": [],
                "reauth_required": False,
            },
            error_code=None,
        )


def test_connection_status_preserves_opaque_provider_account_id() -> None:
    registry = ConnectorRuntimeRegistry()
    registry.register("google_workspace", _RuntimeHandle())  # type: ignore[arg-type]
    adapter = McpOAuthCredentialAdapter(
        runtime_registry=registry,
        mcp_client=_Client(),  # type: ignore[arg-type]
    )

    status = adapter.get_connection_status("google_workspace")

    assert status.connection_status == "CONNECTED"
    assert status.account_id == "google-subject"
    assert status.display_email == "user@example.com"
