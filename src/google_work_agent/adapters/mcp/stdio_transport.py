"""Runtime summary provider backed by MCP and Google connection metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    StdioMCPClientAdapter,
)
from google_work_agent.ports import RuntimeStatusProvider, RuntimeSummary
from google_work_agent.ports.connector.oauth_credential_port import OAuthCredentialPort


@dataclass(frozen=True, slots=True)
class MCPRuntimeStatusProvider(RuntimeStatusProvider):
    google_provider: OAuthCredentialPort
    connector_id: str
    api_llm: str
    ollama: str
    deployment_profile: str
    transport: StdioMCPClientAdapter | None = None
    llm: dict[str, object] | None = None

    def get_summary(self) -> RuntimeSummary:
        try:
            connection = self.google_provider.get_connection_status(self.connector_id)
        except RuntimeError as error:
            connection = None
            google_status = "ERROR"
            google_connection: dict[str, object] = {
                "connected": False,
                "credential_state": google_status,
                "safe_error_code": str(error),
            }
        else:
            google_status = connection.connection_status
            google_connection = asdict(connection)
        if self.transport is not None:
            runtime = self.transport.runtime_metadata()
        else:
            raise RuntimeError("MCP runtime status source is not configured")
        return RuntimeSummary(
            google=google_status,
            mcp=runtime.process_status,
            api_llm=self.api_llm,
            ollama=self.ollama,
            deployment_profile=self.deployment_profile,
            recovery_required_run_ids=(),
            open_run_ids=(),
            google_connection=google_connection,
            mcp_runtime=asdict(runtime),
            llm=self.llm,
        )
