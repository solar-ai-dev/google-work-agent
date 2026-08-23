from __future__ import annotations

from google_work_agent.adapters.mcp import MCPRuntimeStatusProvider
from google_work_agent.ports import (
    DeliveryCertainty,
    MCPRuntimeMetadata,
    MCPTransportError,
    MCPTransportErrorCode,
)


class _MissingOAuthProvider:
    def get_connection_status(self):  # type: ignore[no-untyped-def]
        raise MCPTransportError(
            code=MCPTransportErrorCode.CONFIGURATION_ERROR,
            message="GOOGLE_OAUTH_CLIENT_ID_MISSING",
            delivery_certainty=DeliveryCertainty.NOT_SENT,
        )


class _Runtime:
    def health(self) -> MCPRuntimeMetadata:
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
        api_llm="NOT_CONFIGURED",
        ollama="NOT_CONFIGURED",
        deployment_profile="LOCAL_CAPABLE",
        runtime=_Runtime(),  # type: ignore[arg-type]
    )

    summary = provider.get_summary()

    assert summary.google == "NOT_CONFIGURED"
    assert summary.mcp == "READY"
    assert summary.google_connection == {
        "connected": False,
        "credential_state": "NOT_CONFIGURED",
        "safe_error_code": "GOOGLE_OAUTH_CLIENT_ID_MISSING",
    }
