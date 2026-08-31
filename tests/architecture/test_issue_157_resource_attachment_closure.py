from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "google_work_agent"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _class_definitions(symbol: str) -> list[Path]:
    definitions: list[Path] = []
    for path in (SRC / "application").rglob("*.py"):
        tree = ast.parse(_read(path), filename=str(path))
        if any(isinstance(node, ast.ClassDef) and node.name == symbol for node in ast.walk(tree)):
            definitions.append(path)
    return definitions


def test_resource_routes_only_call_composition_injected_exact_handlers() -> None:
    route = _read(SRC / "api" / "routes" / "resources.py")
    dependencies = _read(SRC / "api" / "dependencies" / "resources.py")
    composition = _read(SRC / "api" / "composition.py")
    handlers = (
        "ListTaskListsHandler",
        "ListCalendarsHandler",
        "ListResourcesHandler",
        "GetResourceCountHandler",
        "GetResourceDetailHandler",
        "GetTaskResourceDetailHandler",
        "GetCalendarResourceDetailHandler",
    )
    for handler in handlers:
        assert f"{handler}(" not in route
        assert handler in dependencies
        assert f"{handler}(" in composition
    assert ".adapters." not in route
    assert "execute_read(" not in route


def test_resource_continuations_are_local_session_account_bound_and_expiring() -> None:
    query = _read(SRC / "application" / "use_cases" / "resource" / "list_resources.py")
    containers = _read(
        SRC / "application" / "use_cases" / "resource" / "list_task_lists.py"
    ) + _read(SRC / "application" / "use_cases" / "resource" / "list_calendars.py")
    store = _read(
        SRC / "application" / "use_cases" / "resource" / "opaque_continuation_access.py"
    )
    assert "session_digest" in query and "account_id" in query
    assert containers.count("session_digest") >= 2
    assert containers.count("account_id") >= 2
    assert "provider_page_token" in store
    assert "expires_at_ms" in store
    assert "LocalResourceContinuationStore" in containers


def test_selection_handle_has_one_issuer_and_resolver_authority() -> None:
    assert _class_definitions("IssueSelectionHandle") == [
        SRC / "application" / "use_cases" / "resource" / "issue_selection_handle.py"
    ]
    assert _class_definitions("ResolveSelectionHandle") == [
        SRC / "application" / "use_cases" / "resource" / "resolve_selection_handle.py"
    ]
    issuer = _read(
        SRC / "application" / "use_cases" / "resource" / "issue_selection_handle.py"
    )
    for field in (
        "service_instance_id",
        "session_digest",
        "account_id",
        "connector_id",
        "resource_type",
        "resource_id",
        "parent_resource_id",
        "expires_at_ms",
    ):
        assert field in issuer


def test_attachment_route_is_singular_multipart_transport_only() -> None:
    route = _read(SRC / "api" / "routes" / "attachments.py")
    dependencies = _read(SRC / "api" / "dependencies" / "attachments.py")
    frontend = _read(ROOT / "frontend" / "src" / "api" / "index.ts")
    assert "def create_router(" not in route
    assert "injected_dependencies" not in route
    assert "UploadFile" in route and "Form(" in route and "File(" in route
    assert "data_base64" not in route + frontend
    assert "command_id=body.command_id" in route
    assert "command_id=request.state.request_id" not in route
    assert "get_attachment_handler: Callable" not in dependencies
    assert "create_staged_attachment_handler: Callable" not in dependencies
    assert "FormData" in frontend
    assert ".adapters." not in route
    assert "Path(" not in route and "open(" not in route
