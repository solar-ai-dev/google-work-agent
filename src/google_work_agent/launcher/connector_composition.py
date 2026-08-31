"""Development connector construction and startup composition."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from google_work_agent.adapters.connectors.google.workspace.composition import (
    GOOGLE_WORKSPACE_CONNECTOR_ID,
    GoogleWorkspaceConnector,
    build_google_workspace_connector_descriptor,
)
from google_work_agent.adapters.connectors.runtime.connector_runtime_registry import (
    ConnectorRuntimeRegistry,
)
from google_work_agent.adapters.connectors.runtime.load_installed_connector_manifest import (
    InstalledConnectorManifestV1,
    load_installed_connector_manifest,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MCPArtifactConfig,
    calculate_file_sha256,
)
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    ATTACHMENT_STAGING_DIR_ENV,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.launcher.development_constants import (
    MCP_MANIFEST_VERSION,
)

GOOGLE_WORKSPACE_MCP_MODULE = (
    "google_work_agent.adapters.connectors.google.workspace.mcp_server.entrypoint"
)


@dataclass(frozen=True, slots=True)
class DevelopmentConnectorBundle:
    runtime_registry: ConnectorRuntimeRegistry
    tool_registry: SignedToolRegistry
    installed_manifest: InstalledConnectorManifestV1
    google_connector: GoogleWorkspaceConnector


def build_connectors(
    *,
    mcp_manifest_path: Path,
    service_instance_id: str,
    attachment_staging_dir: Path,
    python_executable: Path,
    working_directory: Path,
    mcp_module_name: str = GOOGLE_WORKSPACE_MCP_MODULE,
) -> DevelopmentConnectorBundle:
    tool_registry = load_signed_tool_registry()
    installed_manifest = load_installed_connector_manifest()
    installed_connector = installed_manifest.get_required(GOOGLE_WORKSPACE_CONNECTOR_ID)
    if (
        installed_connector.provider_namespace != "google"
        or installed_connector.connector_package != "workspace"
        or not installed_connector.tool_projection_path.endswith(
            "/google_workspace/tool-descriptor-projection-v1.json"
        )
    ):
        raise ValueError("installed Google Workspace connector binding is invalid")
    runtime_registry = ConnectorRuntimeRegistry()
    descriptor = build_google_workspace_connector_descriptor(
        MCPArtifactConfig(
            executable_path=str(python_executable),
            manifest_path=str(mcp_manifest_path),
            expected_binary_sha256=calculate_file_sha256(python_executable),
            expected_manifest_sha256=calculate_file_sha256(mcp_manifest_path),
            expected_manifest_version=MCP_MANIFEST_VERSION,
            expected_protocol_version=MCP_MANIFEST_VERSION,
            expected_registry_manifest_hash=tool_registry.entries_hash,
            startup_timeout_ms=5_000,
            request_timeout_ms=30_000,
            max_restart_count=1,
            environment="DEVELOPMENT",
            service_instance_id=service_instance_id,
            module_name=mcp_module_name,
            working_directory=str(working_directory),
            extra_environment={ATTACHMENT_STAGING_DIR_ENV: str(attachment_staging_dir)},
        ),
        expected_tool_descriptors=tuple(
            tool_registry.descriptor_expectations(GOOGLE_WORKSPACE_CONNECTOR_ID)
        ),
    )
    google_connector = GoogleWorkspaceConnector(
        descriptor=descriptor,
        runtime_registry=runtime_registry,
    )
    google_connector.start()
    return DevelopmentConnectorBundle(
        runtime_registry=runtime_registry,
        tool_registry=tool_registry,
        installed_manifest=installed_manifest,
        google_connector=google_connector,
    )
