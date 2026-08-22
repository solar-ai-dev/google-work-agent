from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"
ASSIGNED_SQLITE = {
    "SQLiteCommandReceiptRepository",
    "SQLiteAuditRepository",
    "SQLiteTraceRepository",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_symbols(path: Path, module: str) -> set[str]:
    symbols: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, ast.ImportFrom) and node.module == module:
            symbols.update(alias.asname or alias.name for alias in node.names)
    return symbols


def _all_imported_symbols(path: Path) -> set[str]:
    symbols: set[str] = set()
    for node in _tree(path).body:
        if isinstance(node, ast.ImportFrom):
            symbols.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            symbols.update(alias.asname or alias.name for alias in node.names)
    return symbols


def _class_names(path: Path) -> set[str]:
    return {node.name for node in _tree(path).body if isinstance(node, ast.ClassDef)}


def _internal_import_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return {module for module in modules if module.startswith("google_work_agent.")}


def test_receipt_audit_trace_ports_are_routed_to_owner_modules() -> None:
    barrel = SRC / "ports" / "__init__.py"
    assert "CommandReceiptRepository" in _imported_symbols(
        barrel, "google_work_agent.ports.persistence.command_receipt_repository"
    )
    assert "AuditRepository" in _imported_symbols(
        barrel, "google_work_agent.ports.persistence.audit_repository"
    )
    assert "TraceRepository" in _imported_symbols(
        barrel, "google_work_agent.ports.persistence.trace_repository"
    )

    broad = _imported_symbols(barrel, "google_work_agent.ports.repositories")
    assert "CommandReceiptRepository" not in broad
    assert "AuditRepository" not in broad
    assert "TraceRepository" not in broad


def test_receipt_audit_trace_sqlite_are_owner_local_not_parent_barrel_exports() -> None:
    parent_barrel = SRC / "adapters" / "persistence" / "__init__.py"
    assert ASSIGNED_SQLITE.isdisjoint(_all_imported_symbols(parent_barrel))
    parent_source = parent_barrel.read_text(encoding="utf-8")
    assert all(symbol not in parent_source for symbol in ASSIGNED_SQLITE)

    owner_modules = {
        "SQLiteCommandReceiptRepository": (
            SRC
            / "adapters"
            / "persistence"
            / "sqlite"
            / "repositories"
            / "command_receipt_repository.py"
        ),
        "SQLiteAuditRepository": (
            SRC
            / "adapters"
            / "persistence"
            / "sqlite"
            / "repositories"
            / "audit_repository.py"
        ),
        "SQLiteTraceRepository": (
            SRC
            / "adapters"
            / "persistence"
            / "sqlite"
            / "repositories"
            / "trace_repository.py"
        ),
    }
    for symbol, path in owner_modules.items():
        assert path.exists()
        assert symbol in _class_names(path)


def test_production_uow_selects_owner_local_sqlite_authorities() -> None:
    uow = SRC / "adapters" / "persistence" / "unit_of_work.py"
    assert "SQLiteCommandReceiptRepository" in _imported_symbols(
        uow,
        "google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository",
    )
    assert "SQLiteAuditRepository" in _imported_symbols(
        uow, "google_work_agent.adapters.persistence.sqlite.repositories.audit_repository"
    )
    assert "SQLiteTraceRepository" in _imported_symbols(
        uow, "google_work_agent.adapters.persistence.sqlite.repositories.trace_repository"
    )
    broad = _imported_symbols(uow, "google_work_agent.adapters.persistence.repositories")
    assert ASSIGNED_SQLITE.isdisjoint(broad)


def test_legacy_secret_boundary_concrete_authority_is_retired() -> None:
    assert not (SRC / "adapters" / "persistence" / "secret_boundary.py").exists()


def test_command_receipt_owner_preserves_durable_cancel_intent_query() -> None:
    path = (
        SRC
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "command_receipt_repository.py"
    )
    repository = next(
        node
        for node in _tree(path).body
        if isinstance(node, ast.ClassDef) and node.name == "SQLiteCommandReceiptRepository"
    )
    methods = {
        node.name
        for node in repository.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {
        "get_by_command_id",
        "add_received",
        "finish",
        "finish_json",
        "has_applied_request_cancel",
    } <= methods
    source = path.read_text(encoding="utf-8")
    assert "RequestRunCancellation" in source
    assert "TRANSITION_APPLIED" in source


def test_audit_trace_remain_separate_and_use_lower_layer_sanitization() -> None:
    audit = (
        SRC
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "audit_repository.py"
    )
    trace = (
        SRC
        / "adapters"
        / "persistence"
        / "sqlite"
        / "repositories"
        / "trace_repository.py"
    )
    assert _class_names(audit) == {"SQLiteAuditRepository"}
    assert _class_names(trace) == {"SQLiteTraceRepository"}

    for path, field_name, insert_sql in (
        (audit, "metadata_json", "INSERT INTO audit_events"),
        (trace, "payload_json", "INSERT INTO trace_events"),
    ):
        modules = _internal_import_modules(path)
        assert not any(module.startswith("google_work_agent.application") for module in modules)
        assert "sanitize_persistent_event_json" in _imported_symbols(
            path, "google_work_agent.ports.observability"
        )
        source = path.read_text(encoding="utf-8")
        sanitizer_call = f"sanitize_persistent_event_json(event.{field_name})"
        assert sanitizer_call in source
        assert source.index(sanitizer_call) < source.index(insert_sql)


def test_persistence_observability_shared_contract_has_single_lower_layer_authority() -> None:
    contract = SRC / "ports" / "observability.py"
    application = SRC / "application" / "observability.py"
    assert {
        "sanitize_persistent_event_json",
        "create_event_envelope",
        "serialize_event_envelope",
    } <= {
        node.name
        for node in _tree(contract).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    app_functions = {
        node.name
        for node in _tree(application).body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "sanitize_persistent_event_json" not in app_functions
    assert "create_event_envelope" not in app_functions
    assert "serialize_event_envelope" not in app_functions
    assert "sanitize_persistent_event_json" in _imported_symbols(
        application, "google_work_agent.ports.observability"
    )
