"""Final integrated Local API transport and authority gates for issue #159."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute

from google_work_agent.api.app import create_app
from google_work_agent.api.composition import DeferredApiContainer

ROOT = Path(__file__).resolve().parents[2]
API = ROOT / "src" / "google_work_agent" / "api"

_PRODUCT_ROUTES = {
    ("DELETE", "/api/v1/credentials/llm/{provider}"),
    ("GET", "/api/v1/backups"),
    ("GET", "/api/v1/connections/google/status"),
    ("GET", "/api/v1/conversations"),
    ("GET", "/api/v1/conversations/{conversation_id}/history"),
    ("GET", "/api/v1/credentials/llm/{provider}"),
    ("GET", "/api/v1/gmail/messages/{message_id}/attachments/{attachment_id}"),
    ("GET", "/api/v1/identity/google-account"),
    ("GET", "/api/v1/resources/calendar"),
    ("GET", "/api/v1/resources/calendar/{resource_id}"),
    ("GET", "/api/v1/resources/calendars"),
    ("GET", "/api/v1/resources/gmail"),
    ("GET", "/api/v1/resources/gmail/count"),
    ("GET", "/api/v1/resources/gmail/{resource_id}"),
    ("GET", "/api/v1/resources/task-lists"),
    ("GET", "/api/v1/resources/tasks"),
    ("GET", "/api/v1/resources/tasks/{resource_id}"),
    ("GET", "/api/v1/runs/{run_id}"),
    ("GET", "/api/v1/runs/{run_id}/context"),
    ("GET", "/api/v1/runs/{run_id}/events"),
    ("GET", "/api/v1/runtime"),
    ("GET", "/api/v1/settings"),
    ("POST", "/api/v1/actions/{action_id}/approve"),
    ("POST", "/api/v1/actions/{action_id}/modify"),
    ("POST", "/api/v1/actions/{action_id}/prepare-retry"),
    ("POST", "/api/v1/actions/{action_id}/reject"),
    ("POST", "/api/v1/attachments/stage"),
    ("POST", "/api/v1/backups"),
    ("POST", "/api/v1/connections/google/disconnect"),
    ("POST", "/api/v1/connections/google/start"),
    ("POST", "/api/v1/control/shutdown"),
    ("POST", "/api/v1/conversations"),
    ("POST", "/api/v1/diagnostics/bundles"),
    ("POST", "/api/v1/restore"),
    ("POST", "/api/v1/runs"),
    ("POST", "/api/v1/runs/{run_id}/cancel"),
    ("POST", "/api/v1/runs/{run_id}/confirm"),
    ("POST", "/api/v1/runs/{run_id}/context-adjustments"),
    ("POST", "/api/v1/runs/{run_id}/resolve-recovery"),
    ("POST", "/api/v1/runs/{run_id}/resume"),
    ("POST", "/api/v1/runtime/mode"),
    ("POST", "/api/v1/session/bootstrap"),
    ("PUT", "/api/v1/credentials/llm/{provider}"),
    ("PUT", "/api/v1/settings"),
}
_EXCEPTION_ROUTES = {("GET", "/health/live"), ("GET", "/health/ready")}
_FALLBACK_ROUTES = {
    (method, "/api/v1/{path:path}") for method in ("DELETE", "GET", "HEAD", "PATCH", "POST", "PUT")
}


def _routes() -> list[APIRoute]:
    container = DeferredApiContainer(
        host="127.0.0.1",
        port=8899,
        service_instance_id="route-census",
        bootstrap_secret="x" * 32,
        core_builder=lambda **_kwargs: None,  # never invoked by route census
    )
    app = create_app(container)  # type: ignore[arg-type]

    def walk(router: object) -> list[APIRoute]:
        result: list[APIRoute] = []
        for route in router.routes:  # type: ignore[attr-defined]
            original = getattr(route, "original_router", None)
            if original is not None:
                result.extend(walk(original))
            elif isinstance(route, APIRoute):
                result.append(route)
        return result

    return walk(app.router)


def test_constructed_application_route_table_is_exact_and_fully_accounted() -> None:
    actual = {(method, route.path) for route in _routes() for method in route.methods or set()}
    assert actual == _PRODUCT_ROUTES | _EXCEPTION_ROUTES | _FALLBACK_ROUTES
    assert len(actual) == 52


def test_product_routes_have_no_direct_dict_response_or_untyped_resource_contract() -> None:
    routes = _routes()
    by_path = {(next(iter(route.methods or set())), route.path): route for route in routes}
    resource_models = {
        "/api/v1/resources/task-lists": "TaskListContainerListResponseV1",
        "/api/v1/resources/calendars": "CalendarContainerListResponseV1",
        "/api/v1/resources/gmail": "ResourceListResponse",
        "/api/v1/resources/tasks": "ResourceListResponse",
        "/api/v1/resources/calendar": "ResourceListResponse",
        "/api/v1/resources/gmail/count": "ResourceCountResponse",
        "/api/v1/resources/gmail/{resource_id}": "GmailResourceDetailResponse",
        "/api/v1/resources/tasks/{resource_id}": "TaskResourceDetailResponseV1",
        "/api/v1/resources/calendar/{resource_id}": "CalendarResourceDetailResponseV1",
    }
    for path, expected in resource_models.items():
        route = by_path[("GET", path)]
        assert route.response_model is not None
        assert route.response_model.__name__ == expected

    for path in (API / "routes").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.returns is not None:
                assert ast.unparse(node.returns) != "dict[str, object]", path


def test_every_route_module_is_registered_and_has_no_concrete_adapter_dependency() -> None:
    app_source = (API / "app.py").read_text(encoding="utf-8")
    registered_names = {
        "actions",
        "api_fallbacks",
        "attachments",
        "conversations",
        "diagnostics",
        "frontend_assets",
        "google_connections",
        "health",
        "identities",
        "llm_connections",
        "resources",
        "runs",
        "runtime_summaries",
        "session",
        "settings",
    }
    actual_names = {path.stem for path in (API / "routes").glob("*.py") if path.stem != "__init__"}
    assert actual_names == registered_names
    for name in registered_names:
        assert name in app_source
        source = (API / "routes" / f"{name}.py").read_text(encoding="utf-8")
        assert "google_work_agent.adapters" not in source
        assert "sqlite3" not in source
        assert "execute_read(" not in source
        assert "execute_write(" not in source


def test_app_and_production_composition_have_one_authority_each() -> None:
    sources = list(ROOT.joinpath("src/google_work_agent").rglob("*.py"))
    create_app_owners = [path for path in sources if "def create_app(" in path.read_text("utf-8")]
    runtime_owners = [
        path for path in sources if "def build_production_runtime(" in path.read_text("utf-8")
    ]
    assert create_app_owners == [API / "app.py"]
    assert runtime_owners == [API / "composition.py"]


def test_production_docs_openapi_and_legacy_product_routes_are_absent() -> None:
    app = create_app(
        DeferredApiContainer(
            host="127.0.0.1",
            port=8899,
            service_instance_id="route-census",
            bootstrap_secret="x" * 32,
            core_builder=lambda **_kwargs: None,
        )  # type: ignore[arg-type]
    )
    assert app.docs_url is None
    assert app.redoc_url is None
    assert app.openapi_url is None
    route_text = "\n".join(
        path.read_text(encoding="utf-8") for path in (API / "routes").glob("*.py")
    )
    assert "/llm/test" not in route_text
    assert 'prefix="/api"' not in route_text
