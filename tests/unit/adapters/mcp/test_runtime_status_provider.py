from __future__ import annotations

from google_work_agent.adapters.mcp.stdio_transport import MCPRuntimeStatusProvider
from google_work_agent.ports import (
    MCPRuntimeMetadata,
)
from google_work_agent.ports.connector.oauth_credential_port import ConnectionMetadataV1


class _MissingOAuthProvider:
    def get_connection_status(self, connector_id: str):  # type: ignore[no-untyped-def]
        assert connector_id == "google_workspace"
        return ConnectionMetadataV1(
            schema_version=1,
            connector_id=connector_id,
            account_id=None,
            display_email=None,
            connection_status="UNAVAILABLE",
            granted_scopes=(),
            missing_required_scopes=("openid",),
        )


class _Runtime:
    def runtime_metadata(self) -> MCPRuntimeMetadata:
        return MCPRuntimeMetadata(
            process_status="READY",
            protocol_version="1",
            manifest_version="1",
            tool_registry_version="1",
            available_tool_count=12,
            last_safe_error_code=None,
            restart_count=0,
            process_instance_id="mcp-1",
        )


def test_runtime_summary_projects_missing_oauth_configuration_without_failing() -> None:
    provider = MCPRuntimeStatusProvider(
        google_provider=_MissingOAuthProvider(),  # type: ignore[arg-type]
        connector_id="google_workspace",
        api_llm="NOT_CONFIGURED",
        ollama="NOT_CONFIGURED",
        deployment_profile="LOCAL_CAPABLE",
        transport=_Runtime(),  # type: ignore[arg-type]
    )

    summary = provider.get_summary()

    assert summary.google == "UNAVAILABLE"
    assert summary.mcp == "READY"
    assert summary.google_connection == {
        "schema_version": 1,
        "connector_id": "google_workspace",
        "account_id": None,
        "display_email": None,
        "connection_status": "UNAVAILABLE",
        "granted_scopes": (),
        "missing_required_scopes": ("openid",),
    }
