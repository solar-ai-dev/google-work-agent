"""Runtime summary provider backed by MCP and Google connection metadata."""

from __future__ import annotations

from dataclasses import asdict, dataclass

from google_work_agent.ports import (
    ConnectorRuntimeHandle,
    GoogleOAuthCredentialProvider,
    MCPTransport,
    RuntimeStatusProvider,
    RuntimeSummary,
)


@dataclass(frozen=True, slots=True)
class MCPRuntimeStatusProvider(RuntimeStatusProvider):
    google_provider: GoogleOAuthCredentialProvider
    api_llm: str
    ollama: str
    deployment_profile: str
    runtime: ConnectorRuntimeHandle | None = None
    transport: MCPTransport | None = None
    llm: dict[str, object] | None = None

    def get_summary(self) -> RuntimeSummary:
        connection = self.google_provider.get_connection_status()
        if self.runtime is not None:
            runtime = self.runtime.health()
        elif self.transport is not None:
            runtime = self.transport.runtime_metadata()
        else:
            raise RuntimeError("MCP runtime status source is not configured")
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
            llm=self.llm,
        )
