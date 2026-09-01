"""FastAPI application composition for the local product core."""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any, BinaryIO, cast

from fastapi import FastAPI

from google_work_agent.adapters.runtime.safe_mode import SafeModeController
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

        def build_core(
            *,
            host: str,
            port: int,
            bootstrap_secret: str,
            service_instance_id: str,
            safe_mode_controller: SafeModeController,
        ) -> ApiContainer:
            return build_production_runtime(
                host=host,
                port=port,
                bootstrap_secret=bootstrap_secret,
                service_instance_id=service_instance_id,
                safe_mode_controller=safe_mode_controller,
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
                verified_release_files=production_config.verified_release_files,
                code_signature_verified_paths=(production_config.code_signature_verified_paths),
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
                frontend_site=production_config.verified_frontend_site(),
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


def _run_installed_service(
    argv: Sequence[str] | None = None,
    *,
    input_stream: BinaryIO | None = None,
    executable_path: Path | None = None,
) -> int:
    """Consume one Launcher handoff and run the installed uvicorn service."""

    try:
        parser = argparse.ArgumentParser(description="Run Google Work Agent service")
        parser.add_argument("--host", required=True)
        parser.add_argument("--port", required=True, type=int)
        parser.add_argument("--data-dir", required=True, type=Path)
        arguments = parser.parse_args(argv)
        if (
            arguments.host != "127.0.0.1"
            or not 1 <= arguments.port <= 65535
            or not arguments.data_dir.is_absolute()
        ):
            raise ValueError("installed service boundary is invalid")
        payload = _read_launcher_handoff(
            input_stream if input_stream is not None else sys.stdin.buffer
        )
        service_instance_id = _required_payload_string(payload, "service_instance_id")
        bootstrap_secret = _required_payload_string(payload, "bootstrap_secret")
        signed_build_config = payload["signed_build_config"]
        if not isinstance(signed_build_config, dict):
            raise ValueError("signed build configuration is invalid")
        executable = (executable_path or Path(sys.executable)).resolve()
        install_root = executable.parent.parent
        production_config = ProductionRuntimeConfig.from_signed_build_config(
            cast(dict[str, object], signed_build_config),
            runtime_root=arguments.data_dir.resolve(),
            working_directory=install_root,
            verified_release_files=payload["verified_release_files"],
            code_signature_verified_paths=payload["code_signature_verified_paths"],
        )

        from uvicorn import Config, Server

        application = create_app(
            production_config=production_config,
            host=arguments.host,
            port=arguments.port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
        )
        Server(
            Config(
                application,
                host=arguments.host,
                port=arguments.port,
                access_log=False,
                proxy_headers=False,
                server_header=False,
                date_header=False,
            )
        ).run()
        return 0
    except Exception as error:
        candidate_code = getattr(error, "safe_code", None)
        safe_code = (
            candidate_code
            if isinstance(candidate_code, str)
            and re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", candidate_code)
            else "SERVICE_STARTUP_INPUT_INVALID"
        )
        print(f"Service failed: {safe_code}", file=sys.stderr)
        return 1


def _read_launcher_handoff(stream: BinaryIO) -> dict[str, Any]:
    maximum = 5 * 1024 * 1024
    raw = stream.readline(maximum + 1)
    if not raw or len(raw) > maximum or stream.readline(1):
        raise ValueError("Launcher handoff size is invalid")
    decoded = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    expected = {
        "schema_version",
        "service_instance_id",
        "bootstrap_secret",
        "signed_build_config",
        "verified_release_files",
        "code_signature_verified_paths",
    }
    if not isinstance(decoded, dict) or set(decoded) != expected or decoded["schema_version"] != 1:
        raise ValueError("Launcher handoff schema is invalid")
    return cast(dict[str, Any], decoded)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate Launcher handoff field")
        result[key] = value
    return result


def _required_payload_string(payload: dict[str, Any], field: str) -> str:
    value = payload[field]
    if not isinstance(value, str) or not value:
        raise ValueError(f"Launcher handoff field is invalid: {field}")
    return value


if __name__ == "__main__":
    raise SystemExit(_run_installed_service())
