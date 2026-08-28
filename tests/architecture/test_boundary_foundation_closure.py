from __future__ import annotations

import ast
from pathlib import Path

from google_work_agent.adapters.connectors.google.workspace.mcp_server import dispatch_tool
from google_work_agent.application.tool_registry import load_signed_tool_registry

SRC = Path(__file__).parents[2] / "src" / "google_work_agent"

PORT_METHODS = {
    "ports/connector/connector_read_port.py": {"execute_read"},
    "ports/connector/connector_write_port.py": {"execute_write"},
    "ports/connector/mcp_client_port.py": {"list_tools", "call_tool", "restart_once"},
    "ports/connector/oauth_credential_port.py": {
        "start_authorization",
        "reconcile_authorization_start",
        "refresh_access",
        "get_connection_status",
        "revoke_connection",
        "reconcile_revoke_connection",
    },
    "ports/llm/structured_inference_port.py": {"infer"},
    "ports/llm/llm_credential_port.py": {
        "store_credential",
        "delete_credential",
        "get_credential_status",
        "reconcile_credential",
    },
    "ports/llm/llm_runtime_status_port.py": {"get_status"},
    "ports/keyring/secret_store_port.py": {"put", "get", "delete"},
    "ports/system/checkpoint_port.py": {
        "create_workflow_binding",
        "load_workflow_binding",
        "store_same_run_checkpoint",
        "load_same_run_checkpoint",
        "store_retrieval_head",
        "load_retrieval_head",
        "store_external_llm_scope",
        "load_external_llm_scope",
        "flush",
        "delete_run_checkpoints",
    },
    "ports/system/run_retrieval_cache_port.py": {
        "put_read_result",
        "resolve_read_result",
        "discard_run",
    },
    "ports/system/workflow_execution_port.py": {"submit", "begin_shutdown", "await_drained"},
    "ports/system/settings_port.py": {"get_settings", "update_settings", "reconcile_settings"},
    "ports/system/runtime_mode_port.py": {
        "get_requested_mode",
        "set_requested_mode",
        "reconcile_update",
    },
    "ports/system/backup_port.py": {
        "create_backup",
        "reconcile_backup",
        "restore_backup",
        "reconcile_restore",
        "list_backups",
    },
    "ports/system/diagnostics_port.py": {"create_bundle", "reconcile_bundle"},
    "ports/system/shutdown_port.py": {"request_shutdown", "reconcile_shutdown"},
    "ports/system/operational_command_replay_port.py": {
        "reserve_or_replay",
        "mark_uncertain",
        "store_result",
    },
    "ports/system/attachment_staging_port.py": {
        "stage",
        "reconcile_stage",
        "open_bytes",
        "delete",
    },
    "ports/system/clock_port.py": {"now_ms"},
    "ports/system/uuid_port.py": {"new_uuid"},
    "ports/system/hardware_probe_port.py": {"probe"},
    "ports/system/browser_launcher_port.py": {"open_url"},
    "ports/system/component_circuit_state_port.py": {
        "get_state",
        "record_technical_failure",
        "record_success",
    },
    "ports/system/sse_event_buffer_port.py": {"append", "list_after", "clear_run"},
}


def test_exact_24_canonical_port_method_surfaces() -> None:
    assert len(PORT_METHODS) == 24
    for relative_path, expected_methods in PORT_METHODS.items():
        module = ast.parse((SRC / relative_path).read_text(encoding="utf-8"))
        port = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef) and node.name.endswith("Port")
        )
        actual_methods = {
            node.name
            for node in port.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert actual_methods == expected_methods, relative_path


def test_google_mcp_dispatch_has_exact_signed_registry_operation_set() -> None:
    registry = load_signed_tool_registry()

    assert set(dispatch_tool._OPERATIONS) == {  # noqa: SLF001
        entry.tool_id for entry in registry.entries
    }


def test_removed_boundary_authorities_and_compatibility_paths_are_absent() -> None:
    removed = (
        "adapters/connectors/connector_registry.py",
        "adapters/connectors/execution_router.py",
        "application/connector_registry.py",
        "adapters/llm/api_provider.py",
        "adapters/llm/gemini.py",
        "adapters/llm/ollama.py",
        "adapters/mcp/gateway.py",
        "adapters/mcp/google_workspace_compat.py",
        "ports/connector/migration_contracts",
        "ports/connectors/connector_runtime.py",
        "ports/google_oauth.py",
        "adapters/llm/ollama/credential.py",
    )

    assert not [
        relative
        for relative in removed
        if (SRC / relative).is_file()
        or ((SRC / relative).is_dir() and any((SRC / relative).glob("*.py")))
    ]

    production = "\n".join(path.read_text(encoding="utf-8") for path in SRC.rglob("*.py"))
    assert "GoogleOAuthCredentialProvider" not in production


def test_boundary_adapter_packages_do_not_reexport_concrete_owners() -> None:
    for relative in (
        "adapters/llm/__init__.py",
        "adapters/llm/gemini/__init__.py",
        "adapters/llm/ollama/__init__.py",
        "adapters/mcp/__init__.py",
    ):
        module = ast.parse((SRC / relative).read_text(encoding="utf-8"))
        assert not [node for node in module.body if isinstance(node, (ast.Import, ast.ImportFrom))]


def test_workspace_runtime_routes_public_tools_through_canonical_dispatch() -> None:
    runtime = SRC / "adapters/connectors/google/workspace/mcp_server/workspace_runtime.py"
    source = runtime.read_text(encoding="utf-8")

    assert (
        "from google_work_agent.adapters.connectors.google.workspace.mcp_server."
        "dispatch_tool import (" in source
    )
    assert "dispatch_tool(" in source
    for entry in load_signed_tool_registry().entries:
        assert f'"{entry.tool_id}":' not in source


def test_connector_write_has_one_production_dispatch_caller() -> None:
    callers = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "._connector_write_port.execute_write(" in source:
            callers.append(path.relative_to(SRC).as_posix())

    assert callers == ["application/use_cases/execution_attempt/dispatch_connector_write.py"]
