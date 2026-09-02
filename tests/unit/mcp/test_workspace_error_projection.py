from google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint import (
    _workspace_error_code,
)
from google_work_agent.ports.connector.mcp_client_port import MCPClientPortErrorCode


def test_workspace_reauth__error_survives_the__mcp_transport_contract() -> None:
    assert _workspace_error_code("REAUTH_REQUIRED") == "AUTH_REQUIRED"
    assert MCPClientPortErrorCode("AUTH_REQUIRED") is MCPClientPortErrorCode.AUTH_REQUIRED


def test_non_auth__workspace_rejection_remains__a_tool_rejection() -> None:
    assert _workspace_error_code("INVALID_ARGUMENT") == "TOOL_REJECTED"
