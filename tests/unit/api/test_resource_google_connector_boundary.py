from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "src" / "google_work_agent"
ROUTE_DIR = SRC / "api" / "routes"
USE_CASE_DIR = SRC / "application" / "use_cases"
PROVIDER_PREFIXES = (
    "googleapiclient",
    "google_auth_oauthlib",
    "google.auth",
    "google.oauth2",
    "google.api_core",
    "google.cloud",
)


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _tree(path: Path) -> ast.Module:
    return ast.parse(_source(path), filename=str(path))


def _imports(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def _called_names(path: Path) -> set[str]:
    result: set[str] = set()
    for node in ast.walk(_tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            result.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            result.add(node.func.attr)
    return result


def test_resource_attachment_google_routes_hide_concrete_connector_exceptions() -> None:
    forbidden = (
        "GoogleWorkspaceGatewayError",
        "GoogleWorkspaceErrorCode",
        "MCPTransportError",
        "MCPTransportErrorCode",
        "AttachmentStagingError",
    )
    for route_name in ("resources.py", "attachments.py", "google.py"):
        source = _source(ROUTE_DIR / route_name)
        for symbol in forbidden:
            assert symbol not in source, (route_name, symbol)


def test_routes_actually_invoke_canonical_application_handlers() -> None:
    expected = {
        "resources.py": {
            "ListResourcesHandler",
            "CountResourcesHandler",
            "GetResourceHandler",
        },
        "attachments.py": {
            "FetchAttachmentHandler",
            "StageAttachmentHandler",
        },
        "google.py": {
            "StartOAuthHandler",
            "GetConnectionHandler",
            "DisconnectConnectorHandler",
        },
    }
    for route_name, handlers in expected.items():
        calls = _called_names(ROUTE_DIR / route_name)
        assert handlers <= calls, (route_name, handlers - calls)


def test_route_wire_ownership_keeps_attachment_base64_decode_in_api() -> None:
    calls = _called_names(ROUTE_DIR / "attachments.py")
    assert "b64decode" in calls


def test_owned_routes_and_use_cases_have_zero_provider_sdk_dependencies() -> None:
    paths = [
        ROUTE_DIR / "resources.py",
        ROUTE_DIR / "attachments.py",
        ROUTE_DIR / "google.py",
        *(USE_CASE_DIR / "resource_ref").glob("*.py"),
        *(USE_CASE_DIR / "attachment").glob("*.py"),
        *(USE_CASE_DIR / "connector_connection").glob("*.py"),
    ]
    violations: list[tuple[str, str]] = []
    for path in paths:
        for module in _imports(path):
            if module.startswith(PROVIDER_PREFIXES):
                violations.append((str(path.relative_to(ROOT)), module))
    assert violations == []


def test_application_use_cases_do_not_depend_on_api_schemas() -> None:
    violations: list[tuple[str, str]] = []
    for owner in ("resource_ref", "attachment", "connector_connection"):
        for path in (USE_CASE_DIR / owner).glob("*.py"):
            for module in _imports(path):
                if module.startswith("google_work_agent.api"):
                    violations.append((str(path.relative_to(ROOT)), module))
    assert violations == []


def test_canonical_handlers_do_not_call_broad_legacy_semantic_surfaces() -> None:
    forbidden_calls = {
        "list_gmail_threads",
        "list_tasks",
        "list_calendar_resources",
        "count_gmail_threads",
        "count_tasks",
        "count_calendar_resources",
        "get_gmail_thread_detail",
    }
    resource_paths = (
        USE_CASE_DIR / "resource_ref" / "list_resources.py",
        USE_CASE_DIR / "resource_ref" / "count_resources.py",
        USE_CASE_DIR / "resource_ref" / "get_resource.py",
    )
    for path in resource_paths:
        assert _called_names(path).isdisjoint(forbidden_calls), path

    get_connection = USE_CASE_DIR / "connector_connection" / "get_connection.py"
    imports = _imports(get_connection)
    assert "google_work_agent.application.google_connection" not in imports


def test_disconnect_operation_filename_matches_symbol_grammar() -> None:
    path = USE_CASE_DIR / "connector_connection" / "disconnect_connector.py"
    assert path.is_file()
    assert not (path.parent / "disconnect.py").exists()
    tree = _tree(path)
    classes = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}
    assert {
        "DisconnectConnectorCommand",
        "DisconnectConnectorResult",
        "DisconnectConnectorHandler",
    } <= classes
