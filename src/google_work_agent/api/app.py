"""FastAPI application composition for the local product core."""

from fastapi import FastAPI

from google_work_agent.api.container import ApiContainer
from google_work_agent.api.errors.error_response import install_error_response_handlers
from google_work_agent.api.lifespan import build_lifespan
from google_work_agent.api.middleware.request_body_limit import (
    install_request_body_limit_middleware,
)
from google_work_agent.api.middleware.request_id import install_request_id_middleware
from google_work_agent.api.middleware.response_headers import (
    install_response_header_middleware,
)
from google_work_agent.api.routes import (
    actions,
    api_fallbacks,
    attachments,
    conversations,
    diagnostics,
    events,
    google_connections,
    health_checks,
    identities,
    llm_connections,
    resources,
    runs,
    runtime_summaries,
    sessions,
    settings,
)
from google_work_agent.api.routes.frontend_assets import create_frontend_asset_router
from google_work_agent.api.security.bind import LocalBindPolicy


def create_app(container: ApiContainer) -> FastAPI:
    LocalBindPolicy(host=container.local_bind_host, port=container.local_bind_port).validate()
    docs_url = "/docs" if container.api_docs_enabled else None
    openapi_url = "/openapi.json" if container.api_docs_enabled else None
    app = FastAPI(
        lifespan=build_lifespan(container),
        docs_url=docs_url,
        redoc_url=None,
        openapi_url=openapi_url,
    )
    app.state.container = container

    install_request_id_middleware(app, container)
    install_response_header_middleware(app, container)
    install_request_body_limit_middleware(app, container)
    install_error_response_handlers(app, container)

    for route in (
        health_checks,
        sessions,
        google_connections,
        runtime_summaries,
        identities,
        conversations,
        diagnostics,
        runs,
        actions,
        events,
        resources,
        settings,
        llm_connections,
        attachments,
        api_fallbacks,
    ):
        app.include_router(route.router)

    frontend_router = create_frontend_asset_router(container.frontend_site)
    if frontend_router is not None:
        app.include_router(frontend_router)
    return app
