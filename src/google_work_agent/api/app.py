"""FastAPI app factory for the local product core."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from google_work_agent.api.errors import ApiError, api_error_from_http, api_error_from_validation
from google_work_agent.api.routes import (
    actions,
    conversations,
    events,
    google,
    health,
    identity,
    llm,
    resources,
    runs,
    runtime,
    session,
    settings,
)
from google_work_agent.api.security import DEFAULT_ENDPOINT_POLICY_REGISTRY, LocalBindPolicy
from google_work_agent.api.security.body_limit import is_body_too_large
from google_work_agent.ports import (
    ApiAccessGuard,
    Clock,
    IdGenerator,
    LauncherProbeVerifier,
    OperationalLogSink,
    ReadinessAggregator,
    RunEventPublisher,
    RuntimeStatusProvider,
    WorkflowRuntime,
)

API_CONTRACT_VERSION = "1"


@dataclass(frozen=True, slots=True)
class ApiContainer:
    unit_of_work_factory: Callable[[], Any]
    query_service: Any
    create_conversation_service: Any
    start_run_service: Any
    approve_action_service: Any
    modify_action_service: Any
    reject_action_service: Any
    prepare_retry_service: Any
    cancel_run_service: Any
    resume_run_service: Any
    local_run_coordinator: Any
    workflow_runtime: WorkflowRuntime
    event_publisher: RunEventPublisher
    readiness_aggregator: ReadinessAggregator
    runtime_status_provider: RuntimeStatusProvider
    api_access_guard: ApiAccessGuard
    clock: Clock
    id_generator: IdGenerator
    release_version: str
    environment: str
    service_instance_id: str
    api_contract_version: str = API_CONTRACT_VERSION
    local_bind_host: str = "127.0.0.1"
    local_bind_port: int = 8000
    max_request_body_bytes: int = 64 * 1024
    api_docs_enabled: bool = False
    launcher_probe_verifier: LauncherProbeVerifier | None = None
    bootstrap_grant_store: Any | None = None
    local_session_manager: Any | None = None
    endpoint_policy_registry: Any = DEFAULT_ENDPOINT_POLICY_REGISTRY
    client_address_resolver: Callable[[Request], str | None] | None = None
    operational_log_sink: OperationalLogSink | None = None
    start_google_oauth_service: Any | None = None
    get_google_connection_service: Any | None = None
    disconnect_google_service: Any | None = None
    resource_query_service: Any | None = None
    frontend_site: Any | None = None
    additional_readiness_checks: tuple[Callable[[], Any], ...] = ()
    safe_mode_controller: Any | None = None
    core_initialization_in_progress: bool = False
    get_settings_service: Any | None = None
    patch_settings_service: Any | None = None
    list_backups_service: Any | None = None
    create_backup_service: Any | None = None
    create_restore_plan_service: Any | None = None
    request_shutdown_service: Any | None = None
    get_llm_connection_service: Any | None = None
    store_llm_api_key_service: Any | None = None
    delete_llm_api_key_service: Any | None = None
    test_llm_connection_service: Any | None = None
    resolve_recovery_service: Any | None = None
    startup_callbacks: tuple[Callable[[], Awaitable[None]], ...] = ()
    shutdown_callbacks: tuple[Callable[[], None], ...] = ()


def create_app(container: ApiContainer) -> FastAPI:
    """Create the FastAPI application with explicit dependency injection."""

    LocalBindPolicy(host=container.local_bind_host, port=container.local_bind_port).validate()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        startup_tasks: list[asyncio.Future[None]] = [
            asyncio.ensure_future(callback()) for callback in container.startup_callbacks
        ]
        container.local_run_coordinator.start()
        try:
            yield
        finally:
            try:
                for task in startup_tasks:
                    if not task.done():
                        task.cancel()
                if startup_tasks:
                    await asyncio.wait_for(
                        asyncio.gather(*startup_tasks, return_exceptions=True),
                        timeout=30,
                    )
                container.local_run_coordinator.stop()
            finally:
                _run_shutdown_callbacks(container.shutdown_callbacks)

    docs_url = "/docs" if container.api_docs_enabled else None
    openapi_url = "/openapi.json" if container.api_docs_enabled else None
    app = FastAPI(lifespan=lifespan, docs_url=docs_url, redoc_url=None, openapi_url=openapi_url)
    app.state.container = container

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = container.id_generator.next_id()
        response = await call_next(request)
        response.headers["X-Api-Contract-Version"] = container.api_contract_version
        response.headers["Cache-Control"] = response.headers.get("Cache-Control", "no-store")
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.middleware("http")
    async def body_limit_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        if request.method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
            body = await request.body()
            content_length = request.headers.get("content-length")
            parsed_length = (
                int(content_length)
                if content_length is not None and content_length.isdigit()
                else None
            )
            if is_body_too_large(
                content_length=parsed_length,
                actual_length=len(body),
                limit_bytes=container.max_request_body_bytes,
            ):
                request_id = getattr(request.state, "request_id", None)
                if not isinstance(request_id, str):
                    request_id = container.id_generator.next_id()
                raise ApiError(
                    error_code="INVALID_ARGUMENT",
                    user_message="Request body exceeds the local API limit.",
                    status_code=413,
                    request_id=request_id,
                    detail_code="REQUEST_BODY_TOO_LARGE",
                )
        return await call_next(request)

    @app.exception_handler(ApiError)
    async def api_error_handler(_: Request, error: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=error.status_code,
            content={
                "error_code": error.error_code,
                "user_message": error.user_message,
                "retryable": error.retryable,
                "current_state": error.current_state,
                "request_id": error.request_id,
                "detail_code": error.detail_code,
                "api_contract_version": container.api_contract_version,
            },
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        error: RequestValidationError,
    ) -> JSONResponse:
        api_error = api_error_from_validation(error, request.state.request_id)
        return await api_error_handler(request, api_error)

    @app.exception_handler(Exception)
    async def fallback_error_handler(request: Request, error: Exception) -> JSONResponse:
        from fastapi import HTTPException

        if isinstance(error, HTTPException):
            api_error = api_error_from_http(error, request.state.request_id)
        else:
            api_error = ApiError(
                error_code="INTERNAL_ERROR",
                user_message="처리 중 오류가 발생했습니다.",
                status_code=500,
                request_id=request.state.request_id,
            )
        return await api_error_handler(request, api_error)

    app.include_router(health.router)
    app.include_router(session.router)
    app.include_router(google.router)
    app.include_router(runtime.router)
    app.include_router(identity.router)
    app.include_router(conversations.router)
    app.include_router(runs.router)
    app.include_router(actions.router)
    app.include_router(events.router)
    app.include_router(resources.router)
    app.include_router(settings.router)
    app.include_router(llm.router)

    @app.api_route("/api/v1/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"])
    async def reject_unknown_api_path(request: Request, path: str) -> Response:
        del path
        from google_work_agent.api.dependencies import enforce_access
        from google_work_agent.ports import EndpointPolicy

        enforce_access(request, policy=EndpointPolicy.API_SESSION_REQUIRED)
        raise ApiError(
            error_code="NOT_FOUND",
            user_message="Route not found.",
            status_code=404,
            request_id=request.state.request_id,
            detail_code="API_ROUTE_NOT_FOUND",
        )

    frontend_site = container.frontend_site
    if frontend_site is not None:

        @app.get("/{path:path}")
        async def frontend_entry(path: str) -> Response:
            if path.startswith("api/") or path.startswith("health/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            candidate = frontend_site.resolve_asset(path)
            if candidate is not None and candidate.is_file():
                response = FileResponse(candidate)
                if Path(candidate).name == "index.html":
                    response.headers["Cache-Control"] = "no-cache"
                else:
                    response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
                return response
            if "." not in path and path:
                response = FileResponse(frontend_site.index_path)
                response.headers["Cache-Control"] = "no-cache"
                return response
            if path == "":
                response = FileResponse(frontend_site.index_path)
                response.headers["Cache-Control"] = "no-cache"
                return response
            return JSONResponse(status_code=404, content={"detail": "not found"})

    return app


def _run_shutdown_callbacks(callbacks: tuple[Callable[[], None], ...]) -> None:
    first_error: Exception | None = None
    for callback in callbacks:
        try:
            callback()
        except Exception as error:
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise first_error
