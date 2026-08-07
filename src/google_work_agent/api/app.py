"""FastAPI app factory for the local product core."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from google_work_agent.api.errors import ApiError, api_error_from_http, api_error_from_validation
from google_work_agent.api.routes import actions, conversations, events, health, runs, runtime
from google_work_agent.ports import (
    ApiAccessGuard,
    Clock,
    IdGenerator,
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


def create_app(container: ApiContainer) -> FastAPI:
    """Create the FastAPI application with explicit dependency injection."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.container = container
        container.local_run_coordinator.start()
        try:
            yield
        finally:
            container.local_run_coordinator.stop()

    app = FastAPI(lifespan=lifespan)
    app.state.container = container

    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request.state.request_id = container.id_generator.next_id()
        response = await call_next(request)
        response.headers["X-Api-Contract-Version"] = container.api_contract_version
        return response

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
    app.include_router(runtime.router)
    app.include_router(conversations.router)
    app.include_router(runs.router)
    app.include_router(actions.router)
    app.include_router(events.router)
    return app
