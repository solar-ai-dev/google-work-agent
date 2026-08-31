"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import secrets
import uuid
from pathlib import Path
from typing import NoReturn, cast

from fastapi import FastAPI

from google_work_agent.adapters.runtime import (
    SafeModeController,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import (
    DeferredApiContainer,
    build_production_container,
)
from google_work_agent.api.container import ApiContainer
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.launcher.development_constants import (
    MCP_MANIFEST_VERSION,
    PROJECT_ROOT,
)
from google_work_agent.launcher.development_readiness import (
    DevelopmentReadinessAggregator as DevelopmentReadinessAggregator,
)
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def build_container(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    runtime_root: Path | None = None,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
    safe_mode_controller: SafeModeController | None = None,
    mcp_module_name: str | None = None,
    keyring_store: SecretStorePort | None = None,
) -> ApiContainer:
    """Provide launcher-owned environment values to the API composition root."""
    return build_production_container(
        host=host,
        port=port,
        runtime_root=(runtime_root or PROJECT_ROOT / "runtime" / "development").resolve(),
        working_directory=PROJECT_ROOT,
        mcp_manifest_version=MCP_MANIFEST_VERSION,
        bootstrap_secret=bootstrap_secret,
        service_instance_id=service_instance_id,
        safe_mode_controller=safe_mode_controller,
        mcp_module_name=mcp_module_name,
        keyring_store=keyring_store,
    )


def create_service_app() -> FastAPI:
    """Return an argument-free application factory for Uvicorn."""

    shell = DeferredApiContainer(
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=secrets.token_urlsafe(32),
        core_builder=build_container,
    )
    return create_app(cast(ApiContainer, shell))


def main() -> NoReturn:
    """Run the development service on an explicit loopback address."""

    parser = argparse.ArgumentParser(description="Run the Google Work Agent development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    LocalBindPolicy(host=args.host, port=args.port).validate()
    bootstrap_secret = secrets.token_urlsafe(32)
    container = DeferredApiContainer(
        host=args.host,
        port=args.port,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=bootstrap_secret,
        core_builder=build_container,
    )
    print(
        "Open the Vite development UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={container.service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(create_app(cast(ApiContainer, container)), host=args.host, port=args.port)
    raise SystemExit(0)


if __name__ == "__main__":
    main()
