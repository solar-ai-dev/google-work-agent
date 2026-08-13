"""Development connector construction and startup composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google_work_agent.adapters.connectors import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    GoogleWorkspaceConnector,
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.mcp import (
    MCPArtifactConfig,
    MCPRuntimeStatusProvider,
    calculate_file_sha256,
)
from google_work_agent.adapters.runtime import BuildProfile
from google_work_agent.adapters.runtime.attachment_staging import ATTACHMENT_STAGING_DIR_ENV
from google_work_agent.application.connector_registry import ConnectorRegistry
from google_work_agent.domain import ConnectorToolCatalog
from google_work_agent.domain.google_workspace_tool_registry import (
    build_google_workspace_tool_registry,
)
from google_work_agent.launcher.development_constants import (
    MCP_MANIFEST_VERSION,
    MCP_TOOL_REGISTRY_VERSION,
)


@dataclass(frozen=True, slots=True)
class DevelopmentConnectorBundle:
    registry: ConnectorRegistry
    google_connector: GoogleWorkspaceConnector
    runtime_status_provider: MCPRuntimeStatusProvider


def build_connectors(
    *,
    mcp_manifest_path: Path,
    service_instance_id: str,
    attachment_staging_dir: Path,
    python_executable: Path,
    working_directory: Path,
) -> DevelopmentConnectorBundle:
    tool_catalog = ConnectorToolCatalog()
    tool_catalog.register(
        connector_id=GOOGLE_WORKSPACE_CONNECTOR_ID,
        registry=build_google_workspace_tool_registry(),
    )
    descriptor = build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(python_executable),
            manifest_path=str(mcp_manifest_path),
            expected_binary_sha256=calculate_file_sha256(python_executable),
            expected_manifest_sha256=calculate_file_sha256(mcp_manifest_path),
            expected_manifest_version=MCP_MANIFEST_VERSION,
            expected_protocol_version=MCP_MANIFEST_VERSION,
            expected_tool_registry_version=MCP_TOOL_REGISTRY_VERSION,
            startup_timeout_ms=5_000,
            request_timeout_ms=30_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id=service_instance_id,
            working_directory=str(working_directory),
            extra_environment={ATTACHMENT_STAGING_DIR_ENV: str(attachment_staging_dir)},
        ),
        tool_registry=tool_catalog.registry_for(GOOGLE_WORKSPACE_CONNECTOR_ID),
    )
    google_connector = GoogleWorkspaceConnector(descriptor=descriptor)
    registry = ConnectorRegistry()
    registry.register(google_connector)
    registry.get(GOOGLE_WORKSPACE_CONNECTOR_ID).start()
    return DevelopmentConnectorBundle(
        registry=registry,
        google_connector=google_connector,
        runtime_status_provider=MCPRuntimeStatusProvider(
            google_provider=google_connector.oauth_provider,
            api_llm="NOT_CONFIGURED",
            ollama="NOT_CONFIGURED",
            deployment_profile=BuildProfile.LOCAL_CAPABLE.value,
            runtime=registry.get(GOOGLE_WORKSPACE_CONNECTOR_ID),
        ),
    )
