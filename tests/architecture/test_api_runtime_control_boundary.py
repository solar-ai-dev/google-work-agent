"""Architecture guards for Wave-B API runtime/control ownership."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "src" / "google_work_agent" / "api" / "routes"
USE_CASES = ROOT / "src" / "google_work_agent" / "application" / "use_cases"

RUNTIME_CONTROL_BINDINGS = (
    ("runtime_summaries.py", "get_runtime", "GetRuntimeStatusHandler"),
    ("identities.py", "get_current_google_account", "GetGoogleAccountHandler"),
    ("llm_connections.py", "get_llm_connection", "GetLlmCredentialStatusHandler"),
    ("llm_connections.py", "store_llm_api_key", "StoreLlmCredentialHandler"),
    ("llm_connections.py", "delete_llm_api_key", "DeleteLlmCredentialHandler"),
    ("llm_connections.py", "test_llm_connection", "TestLLMConnectionHandler"),
    ("settings.py", "get_settings", "GetSettingsHandler"),
    ("settings.py", "patch_settings", "UpdateSettingsHandler"),
    ("settings.py", "list_backups", "ListBackupsHandler"),
    ("settings.py", "create_backup", "CreateBackupHandler"),
    ("settings.py", "restore_backup", "RestoreBackupHandler"),
    ("settings.py", "shutdown", "RequestShutdownHandler"),
    ("health_checks.py", "ready", "GetReadinessHandler"),
)
APPLICATION_RUNTIME_CONTROL_OWNERS = (
    "runtime_status",
    "runtime_mode",
    "identity",
    "llm_credential",
    "llm",
    "setting",
    "backup",
    "shutdown",
    "health",
)
PROVIDER_BOUNDARY_ROUTES = (
    "runtime_summaries.py",
    "identities.py",
    "llm_connections.py",
    "settings.py",
    "health_checks.py",
)


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.AST) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            modules.add(f"{'.' * node.level}{node.module or ''}")
    return modules


def _imports_symbol_from_application_use_cases(tree: ast.AST, symbol: str) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if not node.module.startswith("google_work_agent.application.use_cases."):
            continue
        if any(alias.name == symbol for alias in node.names):
            return True
    return False


def _route_function(tree: ast.Module, function_name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return node
    raise AssertionError(f"route endpoint function not found: {function_name}")


def _is_route_endpoint(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in function.decorator_list:
        if not isinstance(decorator, ast.Call) or not isinstance(decorator.func, ast.Attribute):
            continue
        if not isinstance(decorator.func.value, ast.Name) or decorator.func.value.id != "router":
            continue
        if decorator.func.attr in {"get", "post", "put", "patch", "delete"}:
            return True
    return False


def _calls_handler(function: ast.AST, handler_name: str) -> bool:
    """Require the endpoint to execute the imported exact Handler."""
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Attribute) and node.func.attr == "handle":
            constructor = node.func.value.func if isinstance(node.func.value, ast.Call) else None
            if isinstance(constructor, ast.Name) and constructor.id == handler_name:
                return True
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "isinstance"
            and len(node.args) == 2
            and isinstance(node.args[1], ast.Name)
            and node.args[1].id == handler_name
        ):
            return True
    return False


def _runtime_control_application_files() -> list[Path]:
    files: list[Path] = []
    for owner in APPLICATION_RUNTIME_CONTROL_OWNERS:
        owner_root = USE_CASES / owner
        files.extend(path for path in owner_root.rglob("*.py") if path.is_file())
    return files


def _matches_module(module: str, prefix: str) -> bool:
    normalized = module.lstrip(".")
    return normalized == prefix or normalized.startswith(f"{prefix}.")


def test_all_runtime_control_routes_bind_expected_application_handlers() -> None:
    """VAPI4-001: route endpoint -> canonical Handler -> handle(...) must remain exact."""
    assert len(RUNTIME_CONTROL_BINDINGS) == 13
    for route_name, endpoint_name, handler_name in RUNTIME_CONTROL_BINDINGS:
        tree = _parse(ROUTES / route_name)
        endpoint = _route_function(tree, endpoint_name)
        assert _is_route_endpoint(
            endpoint
        ), f"{route_name}:{endpoint_name} is no longer a route endpoint"
        assert _imports_symbol_from_application_use_cases(
            tree, handler_name
        ), f"{route_name}:{endpoint_name} no longer imports canonical {handler_name}"
        assert _calls_handler(
            endpoint, handler_name
        ), f"{route_name}:{endpoint_name} must execute {handler_name}"


def test_runtime_and_identity_routes_do_not_call_broad_query_service_semantics() -> None:
    runtime = (ROUTES / "runtime_summaries.py").read_text(encoding="utf-8")
    identity = (ROUTES / "identities.py").read_text(encoding="utf-8")
    assert ".query_service().get_runtime_summary()" not in runtime
    assert ".query_service().get_current_google_account()" not in identity


def test_runtime_control_application_has_no_api_or_http_reverse_dependency() -> None:
    """VAPI4-002: Application cannot depend back on API/FastAPI/HTTP transport types."""
    prohibited_prefixes = ("google_work_agent.api", "api", "fastapi", "starlette")
    violations: list[str] = []
    for path in _runtime_control_application_files():
        for module in sorted(_imported_modules(_parse(path))):
            if any(_matches_module(module, prefix) for prefix in prohibited_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, "Application -> API/HTTP reverse dependencies found:\n" + "\n".join(
        violations
    )


def test_runtime_control_routes_and_application_do_not_import_provider_or_concrete_adapters() -> (
    None
):
    """Keep runtime-control paths on Ports and away from concrete providers."""
    prohibited_prefixes = (
        "google",
        "googleapiclient",
        "requests",
        "httpx",
        "openai",
        "anthropic",
        "ollama",
        "keyring",
        "google_work_agent.adapters",
        "adapters",
    )
    targets = [ROUTES / route_name for route_name in PROVIDER_BOUNDARY_ROUTES]
    targets.extend(_runtime_control_application_files())
    violations: list[str] = []
    for path in targets:
        for module in sorted(_imported_modules(_parse(path))):
            if any(_matches_module(module, prefix) for prefix in prohibited_prefixes):
                violations.append(f"{path.relative_to(ROOT)} -> {module}")
    assert not violations, (
        "direct Provider SDK/client/concrete adapter imports found:\n" + "\n".join(violations)
    )


def test_application_use_cases_do_not_depend_on_api_schemas() -> None:
    """Keep the pre-existing schema-specific gate as an explicit regression check."""
    for path in _runtime_control_application_files():
        source = path.read_text(encoding="utf-8")
        assert "google_work_agent.api.schemas" not in source


def test_target_routes_do_not_bypass_locked_dependency_boundary() -> None:
    prohibited = ("google_work_agent.api.container", "google_work_agent.api.route_dependencies")
    for route_name in (
        "runtime_summaries.py",
        "identities.py",
        "llm_connections.py",
        "settings.py",
        "sessions.py",
        "health_checks.py",
    ):
        source = (ROUTES / route_name).read_text(encoding="utf-8")
        for dependency in prohibited:
            assert dependency not in source


def test_session_bootstrap_stays_transport_security_owned() -> None:
    source = (ROUTES / "sessions.py").read_text(encoding="utf-8")
    assert "bootstrap_grant_store" in source
    assert "local_session_manager" in source
    assert "httponly=True" in source
    assert 'samesite="strict"' in source
