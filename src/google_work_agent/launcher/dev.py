"""Loopback-only development bootstrap for the local FastAPI service."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path
from typing import NoReturn

from fastapi import FastAPI

from google_work_agent.api.app import create_app
from google_work_agent.api.composition import ProductionRuntimeConfig
from google_work_agent.api.security.bind import LocalBindPolicy
from google_work_agent.launcher.bootstrap_secret import create_bootstrap_secret
from google_work_agent.launcher.development_constants import (
    MCP_MANIFEST_VERSION,
    PROJECT_ROOT,
)
from google_work_agent.launcher.development_readiness import (
    DevelopmentReadinessAggregator as DevelopmentReadinessAggregator,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def development_runtime_config(
    *,
    runtime_root: Path | None = None,
    mcp_module_name: str | None = None,
) -> ProductionRuntimeConfig:
    """Provide development-only paths and manifest identity."""

    return ProductionRuntimeConfig(
        runtime_root=(runtime_root or PROJECT_ROOT / "runtime" / "development").resolve(),
        working_directory=PROJECT_ROOT,
        mcp_manifest_version=MCP_MANIFEST_VERSION,
        mcp_module_name=mcp_module_name,
    )


def create_service_app() -> FastAPI:
    """Return an argument-free application factory for Uvicorn."""

    return create_app(
        production_config=development_runtime_config(),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=create_bootstrap_secret(),
    )


def main() -> NoReturn:
    """Run the development service on an explicit loopback address."""

    parser = argparse.ArgumentParser(description="Run the Google Work Agent development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()
    LocalBindPolicy(host=args.host, port=args.port).validate()
    bootstrap_secret = create_bootstrap_secret()
    service_instance_id = f"dev-{uuid.uuid4()}"
    print(
        "Open the Vite development UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(
        create_app(
            production_config=development_runtime_config(),
            host=args.host,
            port=args.port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
        ),
        host=args.host,
        port=args.port,
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
