"""FastAPI application composition for the local product core."""

from typing import cast

from fastapi import FastAPI

from google_work_agent.api.composition import (
    DeferredApiContainer,
    ProductionRuntimeConfig,
    build_production_runtime,
)
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
    google_connections,
    health,
    identities,
    llm_connections,
    resources,
    runs,
    runtime_summaries,
    session,
    settings,
)
from google_work_agent.api.routes.frontend_assets import create_frontend_asset_router
from google_work_agent.api.security.bind import LocalBindPolicy


def create_app(
    container: ApiContainer | None = None,
    *,
    production_config: ProductionRuntimeConfig | None = None,
    host: str = "127.0.0.1",
    port: int = 8000,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
) -> FastAPI:
    if container is None:
        if production_config is None or bootstrap_secret is None or service_instance_id is None:
            raise ValueError(
                "production_config, bootstrap_secret, and service_instance_id are required"
            )

        def build_core(**runtime_inputs: object) -> ApiContainer:
            return build_production_runtime(
                **runtime_inputs,  # type: ignore[arg-type]
                runtime_root=production_config.runtime_root,
                working_directory=production_config.working_directory,
                release_version=production_config.release_version,
                build_channel=production_config.build_channel,
                deployment_profile=production_config.deployment_profile,
                oauth_environment=production_config.oauth_environment,
                oauth_client_id=production_config.oauth_client_id,
                api_contract_version=production_config.api_contract_version,
                mcp_manifest_version=production_config.mcp_manifest_version,
                policy_version=production_config.policy_version,
                database_migration_version=production_config.database_migration_version,
                configuration_source=production_config.configuration_source,
                mcp_module_name=production_config.mcp_module_name,
                keyring_store=production_config.keyring_store,
            )

        container = cast(
            ApiContainer,
            DeferredApiContainer(
                host=host,
                port=port,
                service_instance_id=service_instance_id,
                bootstrap_secret=bootstrap_secret,
                release_version=production_config.release_version,
                environment=production_config.oauth_environment.value,
                api_contract_version=production_config.api_contract_version,
                deployment_profile=production_config.deployment_profile,
                core_builder=build_core,
            ),
        )
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
        health,
        session,
        google_connections,
        runtime_summaries,
        identities,
        conversations,
        diagnostics,
        runs,
        actions,
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
