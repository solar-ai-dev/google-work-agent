"""FastAPI app factory for the local product core."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from google_work_agent.api.container import API_CONTRACT_VERSION, ApiContainer
from google_work_agent.api.errors import ApiError, api_error_from_http, api_error_from_validation
from google_work_agent.api.routes import (
    actions,
    attachments,
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
from google_work_agent.api.security import LocalBindPolicy
from google_work_agent.api.security.body_limit import is_body_too_large

__all__ = ["API_CONTRACT_VERSION", "ApiContainer", "create_app"]


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
    app.include_router(attachments.router)

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
