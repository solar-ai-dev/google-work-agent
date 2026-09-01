from google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint import (
    _workspace_error_code,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPortErrorCode


def test_workspace_reauth_error_survives_the_mcp_transport_contract() -> None:
    assert _workspace_error_code("REAUTH_REQUIRED") == "AUTH_REQUIRED"
    assert MCPClientPortErrorCode("AUTH_REQUIRED") is MCPClientPortErrorCode.AUTH_REQUIRED


def test_non_auth_workspace_rejection_remains_a_tool_rejection() -> None:
    assert _workspace_error_code("INVALID_ARGUMENT") == "TOOL_REJECTED"
