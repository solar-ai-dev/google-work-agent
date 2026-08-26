"""Runtime summary provider backed by MCP and Google connection metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from google_work_agent.ports import (
    GoogleOAuthCredentialProvider,
    MCPClientPort,
    MCPClientPortError,
    MCPClientPortErrorCode,
    RuntimeStatusProvider,
    RuntimeSummary,
)
from google_work_agent.ports.connectors.connector_runtime import ConnectorRuntimeHandle


@dataclass(frozen=True, slots=True)
class MCPRuntimeStatusProvider(RuntimeStatusProvider):
    google_provider: GoogleOAuthCredentialProvider
    api_llm: str
    ollama: str
    deployment_profile: str
    runtime: ConnectorRuntimeHandle | None = None
    transport: MCPClientPort | None = None
    llm: dict[str, object] | None = None

    def get_summary(self) -> RuntimeSummary:
        try:
            connection = self.google_provider.get_connection_status()
        except MCPClientPortError as error:
            connection = None
            google_status = (
                "NOT_CONFIGURED"
                if error.code is MCPClientPortErrorCode.CONFIGURATION_ERROR
                else "ERROR"
            )
            google_connection: dict[str, object] = {
                "connected": False,
                "credential_state": google_status,
                "safe_error_code": str(error),
            }
        else:
            google_status = connection.credential_state.value
            if connection.connected:
                google_status = "CONNECTED"
            google_connection = asdict(connection)
        if self.runtime is not None:
            runtime = self.runtime.health()
        elif self.transport is not None:
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
