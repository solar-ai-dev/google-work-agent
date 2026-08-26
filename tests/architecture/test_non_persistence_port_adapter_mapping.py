"""The closed 16/07 non-persistence Port-to-Adapter table is executable."""

from __future__ import annotations

import ast
from importlib import import_module
from pathlib import Path

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
    adapter_source = _source(f"{adapter_module.replace('.', '/')}.py")
    adapter_tree = ast.parse(adapter_source)
    class_names = {
        node.name for node in ast.walk(adapter_tree) if isinstance(node, ast.ClassDef)
    }
    adapter_aliases = {
        alias.asname
        for node in ast.walk(adapter_tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert adapter_symbol in class_names
    assert adapter_symbol not in adapter_aliases


def test_non_persistence_p0_bindings_are_closed_and_unique() -> None:
    assert len(NON_PERSISTENCE_P0_BINDINGS) == 24
    assert len({port for port, _adapter in NON_PERSISTENCE_P0_BINDINGS}) == 24
    assert len({adapter for _port, adapter in NON_PERSISTENCE_P0_BINDINGS}) == 24


@pytest.mark.parametrize(
    ("canonical_path", "canonical_symbol", "legacy_symbol"),
    [
        (
            "adapters/connectors/runtime/mcp_oauth_credential.py",
            "McpOAuthCredentialAdapter",
            "MCPGoogleOAuthCredentialProvider",
        ),
        (
            "adapters/llm/runtime/structured_inference_router.py",
            "StructuredInferenceRuntimeRouter",
            None,
        ),
        (
            "adapters/llm/runtime/llm_credential_router.py",
            "LlmCredentialRouter",
            "LLMCredentialService",
        ),
        (
            "adapters/llm/runtime/llm_runtime_status_router.py",
            "LlmRuntimeStatusRouter",
            "LLMRuntimeStatusService",
        ),
        (
            "adapters/system/windows_hardware_probe.py",
            "WindowsHardwareProbeAdapter",
            "DefaultHardwareProbe",
        ),
    ],
)
def test_migrated_concrete_adapter_is_its_own_canonical_implementation(
    canonical_path: str, canonical_symbol: str, legacy_symbol: str | None
) -> None:
    source = _source(canonical_path)
    tree = ast.parse(source)
    class_names = {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}
    assert canonical_symbol in class_names
    assert f" as {canonical_symbol}" not in source
    if legacy_symbol is not None:
        assert legacy_symbol not in source


@pytest.mark.parametrize(
    "legacy_symbol",
    [
        "MCPGoogleOAuthCredentialProvider",
        "LLMCredentialService",
        "LLMRuntimeStatusService",
        "DefaultHardwareProbe",
    ],
)
def test_legacy_concrete_authority_is_absent_from_production_source(legacy_symbol: str) -> None:
    production_sources = (Path("src") / "google_work_agent").rglob("*.py")
    assert all(legacy_symbol not in path.read_text(encoding="utf-8") for path in production_sources)


@pytest.mark.parametrize(
    ("legacy_module", "legacy_symbol"),
    [
        ("google_work_agent.adapters.mcp.oauth", "MCPGoogleOAuthCredentialProvider"),
        ("google_work_agent.adapters.llm", "ApiStructuredLLMProvider"),
        ("google_work_agent.adapters.llm.credentials", "LLMCredentialService"),
        ("google_work_agent.adapters.llm.status", "LLMRuntimeStatusService"),
        ("google_work_agent.adapters.llm.probes", "DefaultHardwareProbe"),
        ("google_work_agent.adapters.runtime", "SettingsService"),
        ("google_work_agent.adapters.runtime", "BackupService"),
        ("google_work_agent.adapters.runtime", "GracefulShutdownCoordinator"),
    ],
)
def test_legacy_concrete_import_and_construction_are_absent_from_production(
    legacy_module: str, legacy_symbol: str
) -> None:
    for source_path in _production_source_paths():
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        imported_symbols = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == legacy_module
            for alias in node.names
        }
        constructed_symbols = {
            node.func.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert legacy_symbol not in imported_symbols, source_path
        assert legacy_symbol not in constructed_symbols, source_path


def test_production_callers_import_the_canonical_concrete_owners() -> None:
    launcher = _source("launcher/dev.py")
    connector = _source("adapters/connectors/google_workspace.py")
    assert "adapters.connectors.runtime.mcp_oauth_credential import (" in connector
    assert "McpOAuthCredentialAdapter," in connector
    assert "adapters.llm.runtime.structured_inference_router import" in launcher
    assert "adapters.llm.runtime.llm_credential_router import LlmCredentialRouter" in launcher
    assert (
        "adapters.llm.runtime.llm_runtime_status_router import LlmRuntimeStatusRouter" in launcher
    )
    assert "adapters.system.windows_hardware_probe import WindowsHardwareProbeAdapter" in launcher


def _source(relative_path: str) -> str:
    return (Path("src") / "google_work_agent" / relative_path).read_text(encoding="utf-8")


def _production_source_paths() -> tuple[Path, ...]:
    return tuple((Path("src") / "google_work_agent").rglob("*.py"))
