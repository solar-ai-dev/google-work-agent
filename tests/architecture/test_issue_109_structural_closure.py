"""Negative proof for Issue #109 structural-authority closure."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src/google_work_agent"
APPLICATION = SRC / "application"


def _production_sources() -> tuple[Path, ...]:
    return tuple(SRC.rglob("*.py"))


def _definitions(symbol: str) -> list[Path]:
    owners: list[Path] = []
    for path in _production_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == symbol
            for node in ast.walk(tree)
        ):
            owners.append(path)
    return owners


def _import_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def test_application_root_contains_no_semantic_production_authority() -> None:
    assert sorted(path.name for path in APPLICATION.glob("*.py")) == ["__init__.py"]


def test_application_orchestration_has_zero_recursive_production_authority() -> None:
    assert not (APPLICATION / "orchestration").exists()
    forbidden_prefix = "google_work_agent.application.orchestration"
    importers = [
        path.relative_to(ROOT).as_posix()
        for path in _production_sources()
        if any(
            module == forbidden_prefix or module.startswith(f"{forbidden_prefix}.")
            for module in _import_modules(path)
        )
    ]
    assert importers == []


def test_broad_contract_and_handoff_authorities_are_absent_from_production() -> None:
    forbidden_names = {"agent_workflow.py", "agent_handoff.py", "contracts.py"}
    assert [
        path.relative_to(ROOT).as_posix()
        for path in _production_sources()
        if path.name in forbidden_names
    ] == []


def test_issue_173_moved_authorities_have_exact_owner_and_live_callers() -> None:
    exact_owners = {
        "route_supervisor": SRC / "adapters/langgraph/main/supervisor.py",
        "RunScopedEvidenceStore": (SRC / "adapters/system/memory/retrieval_evidence_store.py"),
        "account_provider_dispatch": (
            SRC / "application/use_cases/run/account_provider_dispatch.py"
        ),
        "project_action_plan_v2_for_persistence": (
            SRC / "application/use_cases/plan/project_planning_output.py"
        ),
    }
    for symbol, owner in exact_owners.items():
        assert _definitions(symbol) == [owner]
        callers = [
            path.relative_to(ROOT).as_posix()
            for path in _production_sources()
            if path != owner and symbol in path.read_text(encoding="utf-8")
        ]
        assert callers, f"{symbol}: no production caller"


def test_retired_parallel_authorities_and_packages_are_absent() -> None:
    absent = (
        "adapters/persistence/sqlite/query_service.py",
        "adapters/persistence/secret_boundary.py",
        "adapters/connectors/google_workspace.py",
        "adapters/connectors/connector_not_registered_error.py",
        "adapters/mcp/delivery_transport.py",
        "adapters/mcp/stdio_transport.py",
        "ports/query.py",
        "ports/api_access.py",
        "ports/artifact_verifier.py",
        "ports/google_workspace.py",
        "ports/launcher_probe.py",
        "ports/observability.py",
        "ports/observability_events.py",
        "ports/readiness.py",
        "ports/runtime_contracts.py",
        "ports/workflow_runtime.py",
        "application/use_cases/run/resume_run.py",
        "application/use_cases/connector_connection/get_connection.py",
        "application/use_cases/identity/get_google_account.py",
        "application/use_cases/health/get_readiness.py",
        "application/use_cases/settings/get_settings.py",
        "application/use_cases/runtime/request_shutdown.py",
    )
    for relative in absent:
        assert not SRC.joinpath(relative).exists(), relative


def test_ports_root_barrel_has_no_import_or_export_authority() -> None:
    tree = ast.parse((SRC / "ports/__init__.py").read_text(encoding="utf-8"))
    assert not any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in tree.body)
    assert not any(isinstance(node, (ast.Assign, ast.AnnAssign)) for node in tree.body)


def test_legacy_symbols_and_import_paths_have_zero_production_callers() -> None:
    forbidden = (
        "QueryService",
        "ResumeRunHandler",
        "ResumeRunCommand",
        "LLMCredentialStore",
        "LLMRuntimeStatusReader",
        "LLMRuntimeRouter",
        "SecretBoundaryAuditEventRepository",
        "SecretBoundaryTraceEventRepository",
        "from google_work_agent.ports import",
        "google_work_agent.application.start_run",
        "google_work_agent.application.run_lifecycle",
        "google_work_agent.application.google_connection",
    )
    for path in _production_sources():
        source = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in source, f"{path}: {token}"


def test_resume_after_reauth_is_an_independent_exact_handler() -> None:
    path = APPLICATION / "use_cases/run/resume_after_reauth.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    handler = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "ResumeAfterReauthHandler"
    )
    assert handler.bases == []
    assert "REAUTH_COMPLETED only" in path.read_text(encoding="utf-8")


def test_boundary_registries_have_one_production_definition_each() -> None:
    assert _definitions("ConnectorRuntimeRegistry") == [
        SRC / "adapters/connectors/runtime/connector_runtime_registry.py"
    ]
    assert _definitions("SignedToolRegistry") == [
        SRC / "application/tool_registry/signed_tool_registry.py"
    ]


def test_supporting_readers_are_narrow_and_query_service_is_not_reintroduced() -> None:
    assert not (SRC / "adapters/persistence/sqlite/cancel_intent_reader.py").exists()
    assert not (SRC / "adapters/persistence/sqlite/approval_history_reader.py").exists()
    assert not (SRC / "ports/persistence/cancel_intent_reader.py").exists()
    assert not (SRC / "ports/persistence/approval_history_reader.py").exists()
    assert (SRC / "adapters/persistence/sqlite/connected_account_store.py").exists()


def test_google_workspace_composition_has_one_owner_local_location() -> None:
    assert (SRC / "adapters/connectors/google/workspace/composition.py").exists()
    assert not (SRC / "adapters/connectors/google_workspace.py").exists()
