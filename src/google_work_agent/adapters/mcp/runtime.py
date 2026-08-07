"""Runtime summary provider backed by MCP and Google connection metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from google_work_agent.ports import (
    GoogleOAuthCredentialProvider,
    MCPTransport,
    RuntimeStatusProvider,
    RuntimeSummary,
)


@dataclass(frozen=True, slots=True)
class MCPRuntimeStatusProvider(RuntimeStatusProvider):
    google_provider: GoogleOAuthCredentialProvider
    transport: MCPTransport
    api_llm: str
    ollama: str
    deployment_profile: str

    def get_summary(self) -> RuntimeSummary:
        connection = self.google_provider.get_connection_status()
        runtime = self.transport.runtime_metadata()
        google_status = connection.credential_state.value
        if connection.connected:
            google_status = "CONNECTED"
        return RuntimeSummary(
            google=google_status,
            mcp=runtime.process_status,
            api_llm=self.api_llm,
            ollama=self.ollama,
            deployment_profile=self.deployment_profile,
            recovery_required_run_ids=(),
            open_run_ids=(),
            google_connection=asdict(connection),
            mcp_runtime=asdict(runtime),
        )
