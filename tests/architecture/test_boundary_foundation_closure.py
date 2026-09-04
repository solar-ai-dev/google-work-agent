from __future__ import annotations

import ast
from pathlib import Path

from google_work_agent.adapters.connectors.google.workspace.mcp_server import dispatch_tool
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

SRC = Path(__file__).parents[2] / "src" / "google_work_agent"

PORT_METHODS = {
    "ports/connector/connector_read_port.py": {"execute_read"},
    "ports/connector/connector_write_port.py": {"execute_write"},
    "ports/connector/mcp_client_port.py": {
        "process_instance_id",
        "sign_claim_context",
        "list_tools",
        "call_tool",
        "restart_once",
    },
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
    "ports/llm/llm_runtime_status_port.py": {"get_status", "list_local_models"},
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


def test_exact_24__canonical_port__method_surfaces() -> None:
    assert len(PORT_METHODS) == 24
    for relative_path, expected_methods in PORT_METHODS.items():
        module = ast.parse((SRC / relative_path).read_text(encoding="utf-8"))
        port = next(
            node
            for node in module.body
            if isinstance(node, ast.ClassDef)
            and (
                node.name == "CheckpointPort"
                if relative_path == "ports/system/checkpoint_port.py"
                else node.name.endswith("Port")
            )
        )
        actual_methods = {
            node.name
            for node in port.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        assert actual_methods == expected_methods, relative_path


def test_initial_workflow_binding__port_is_narrower__than_checkpoint_port() -> None:
    module = ast.parse((SRC / "ports/system/checkpoint_port.py").read_text(encoding="utf-8"))
    initial = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "InitialWorkflowBindingPort"
    )
    assert {node.name for node in initial.body if isinstance(node, ast.FunctionDef)} == {
        "create_workflow_binding"
    }


def test_google_mcp_dispatch__has_exact_signed__registry_operation_set() -> None:
    registry = load_signed_tool_registry()

    assert set(dispatch_tool._OPERATIONS) == {entry.tool_id for entry in registry.entries}
    assert set(dispatch_tool._INTERNAL_OPERATIONS) == {
        "gmail_get_ui_thread_detail",
        "search_by_recovery_fingerprint",
    }


def test_removed_boundary__authorities_and_compatibility__paths_are_absent() -> None:
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


def test_boundary_adapter__packages_do_not__reexport_concrete_owners() -> None:
    for relative in (
        "adapters/llm/__init__.py",
        "adapters/llm/gemini/__init__.py",
        "adapters/llm/ollama/__init__.py",
    ):
        module = ast.parse((SRC / relative).read_text(encoding="utf-8"))
        assert not [node for node in module.body if isinstance(node, (ast.Import, ast.ImportFrom))]


def test_entrypoint_routes_public__tools_through_operation__per_file_dispatch() -> None:
    from google_work_agent.adapters.connectors.google.workspace.mcp_server.dispatch_tool import (
        _OPERATIONS,
    )

    entrypoint = (SRC / "adapters/connectors/google/workspace/mcp_server/entrypoint.py").read_text(
        encoding="utf-8"
    )
    credential = (
        SRC / "adapters/connectors/google/workspace/mcp_server/credential_provider.py"
    ).read_text(encoding="utf-8")

    assert "dispatch_tool(" in entrypoint
    assert "dispatch_internal_tool(" in entrypoint
    assert "getattr(workspace_tools" not in entrypoint
    assert set(_OPERATIONS) == {entry.tool_id for entry in load_signed_tool_registry().entries}
    for entry in load_signed_tool_registry().entries:
        operation = _OPERATIONS[entry.tool_id]
        operation_path = SRC / (
            operation.__class__.__module__.replace(".", "/") + ".py"
        ).removeprefix("google_work_agent/")
        operation_source = operation_path.read_text(encoding="utf-8")
        assert f"def _{entry.tool_id}(" in operation_source
        assert f"def _{entry.tool_id}(" not in credential
    assert "def _gmail_get_ui_thread_detail(" not in credential
    assert "def _search_by_recovery_fingerprint(" not in credential

    for removed in (
        "workspace_runtime.py",
        "server_runtime.py",
        "provider_operation_runtime.py",
        "oauth_settings.py",
        "tool_contracts.py",
        "internal_capabilities.py",
    ):
        assert not (SRC / f"adapters/connectors/google/workspace/mcp_server/{removed}").exists()


def test_connector_write__has_one__production_dispatch_caller() -> None:
    callers = []
    for path in SRC.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        if "._connector_write_port.execute_write(" in source:
            callers.append(path.relative_to(SRC).as_posix())

    assert callers == ["application/use_cases/execution_attempt/dispatch_connector_write.py"]
