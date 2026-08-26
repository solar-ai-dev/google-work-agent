"""The closed 16/07 non-persistence Port-to-Adapter table is executable."""

from __future__ import annotations

from importlib import import_module

import pytest

from google_work_agent.api.composition import NON_PERSISTENCE_P0_BINDINGS


@pytest.mark.parametrize(
    ("port_module", "port_symbol", "adapter_module", "adapter_symbol"),
    [
        (
            "ports.connector.connector_read_port",
            "ConnectorReadPort",
            "adapters.connectors.runtime.mcp_connector_read",
            "McpConnectorReadAdapter",
        ),
        (
            "ports.connector.connector_write_port",
            "ConnectorWritePort",
            "adapters.connectors.runtime.mcp_connector_write",
            "McpConnectorWriteAdapter",
        ),
        (
            "ports.connector.oauth_credential_port",
            "OAuthCredentialPort",
            "adapters.connectors.runtime.mcp_oauth_credential",
            "McpOAuthCredentialAdapter",
        ),
        (
            "ports.connector.mcp_client_port",
            "MCPClientPort",
            "adapters.connectors.runtime.stdio_mcp_client",
            "StdioMCPClientAdapter",
        ),
        (
            "ports.llm.structured_inference_port",
            "StructuredInferencePort",
            "adapters.llm.runtime.structured_inference_router",
            "StructuredInferenceRuntimeRouter",
        ),
        (
            "ports.llm.llm_credential_port",
            "LlmCredentialPort",
            "adapters.llm.runtime.llm_credential_router",
            "LlmCredentialRouter",
        ),
        (
            "ports.llm.llm_runtime_status_port",
            "LlmRuntimeStatusPort",
            "adapters.llm.runtime.llm_runtime_status_router",
            "LlmRuntimeStatusRouter",
        ),
        (
            "ports.keyring.secret_store_port",
            "SecretStorePort",
            "adapters.keyring.os_keyring_secret_store",
            "OsKeyringSecretStoreAdapter",
        ),
        (
            "ports.system.checkpoint_port",
            "CheckpointPort",
            "adapters.system.sqlite_checkpoint",
            "SqliteCheckpointAdapter",
        ),
        (
            "ports.system.run_retrieval_cache_port",
            "RunRetrievalCachePort",
            "adapters.system.memory.run_retrieval_cache",
            "InMemoryRunRetrievalCache",
        ),
        (
            "ports.system.workflow_execution_port",
            "WorkflowExecutionPort",
            "adapters.langgraph.runtime.background_run_executor",
            "BackgroundRunExecutorAdapter",
        ),
        (
            "ports.system.settings_port",
            "SettingsPort",
            "adapters.system.json_settings",
            "JsonSettingsAdapter",
        ),
        (
            "ports.system.runtime_mode_port",
            "RuntimeModePort",
            "adapters.system.process_runtime_mode",
            "ProcessRuntimeModeAdapter",
        ),
        (
            "ports.system.backup_port",
            "BackupPort",
            "adapters.system.filesystem_backup",
            "FilesystemBackupAdapter",
        ),
        (
            "ports.system.diagnostics_port",
            "DiagnosticsPort",
            "adapters.system.filesystem_diagnostics",
            "FilesystemDiagnosticsAdapter",
        ),
        (
            "ports.system.shutdown_port",
            "ShutdownPort",
            "adapters.system.process_shutdown",
            "ProcessShutdownAdapter",
        ),
        (
            "ports.system.operational_command_replay_port",
            "OperationalCommandReplayPort",
            "adapters.system.filesystem_operational_command_replay",
            "FilesystemOperationalCommandReplayAdapter",
        ),
        (
            "ports.system.attachment_staging_port",
            "AttachmentStagingPort",
            "adapters.system.filesystem_attachment_staging",
            "FilesystemAttachmentStagingAdapter",
        ),
        (
            "ports.system.clock_port",
            "ClockPort",
            "adapters.system.system_clock",
            "SystemClockAdapter",
        ),
        ("ports.system.uuid_port", "UUIDPort", "adapters.system.uuid4", "Uuid4Adapter"),
        (
            "ports.system.hardware_probe_port",
            "HardwareProbePort",
            "adapters.system.windows_hardware_probe",
            "WindowsHardwareProbeAdapter",
        ),
        (
            "ports.system.browser_launcher_port",
            "BrowserLauncherPort",
            "adapters.system.default_browser_launcher",
            "DefaultBrowserLauncherAdapter",
        ),
        (
            "ports.system.component_circuit_state_port",
            "ComponentCircuitStatePort",
            "adapters.system.process_component_circuit_state",
            "ProcessComponentCircuitStateAdapter",
        ),
        (
            "ports.system.sse_event_buffer_port",
            "SseEventBufferPort",
            "adapters.system.memory.sse_event_buffer",
            "InMemorySseEventBuffer",
        ),
    ],
)
def test_canonical_non_persistence_port_adapter_pair_is_importable(
    port_module: str,
    port_symbol: str,
    adapter_module: str,
    adapter_symbol: str,
) -> None:
    assert getattr(import_module(f"google_work_agent.{port_module}"), port_symbol)
    assert getattr(import_module(f"google_work_agent.{adapter_module}"), adapter_symbol)


def test_non_persistence_p0_bindings_are_closed_and_unique() -> None:
    assert len(NON_PERSISTENCE_P0_BINDINGS) == 24
    assert len({port for port, _adapter in NON_PERSISTENCE_P0_BINDINGS}) == 24
    assert len({adapter for _port, adapter in NON_PERSISTENCE_P0_BINDINGS}) == 24
