"""Explicit repository-only development service runner."""

from __future__ import annotations

import argparse
import uuid
from pathlib import Path
from typing import NoReturn

from fastapi import FastAPI
from launcher.bootstrap_secret import create_bootstrap_secret

from google_work_agent.api.app import create_app
from google_work_agent.api.composition import ProductionRuntimeConfig
from google_work_agent.api.security.bind import LocalBindPolicy

PROJECT_ROOT = Path(__file__).resolve().parents[1]
MCP_MANIFEST_VERSION = "2026-08-07.p0"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000


def development_runtime_config(
    *,
    runtime_root: Path | None = None,
    mcp_module_name: str | None = None,
) -> ProductionRuntimeConfig:
    """Supply explicit development values without becoming an installed fallback."""

    return ProductionRuntimeConfig.development(
        runtime_root=(runtime_root or PROJECT_ROOT / "runtime" / "development").resolve(),
        working_directory=PROJECT_ROOT,
        mcp_manifest_version=MCP_MANIFEST_VERSION,
        mcp_module_name=mcp_module_name,
    )


def create_service_app() -> FastAPI:
    """Return an argument-free development factory for Uvicorn."""

    return create_app(
        production_config=development_runtime_config(),
        host=DEFAULT_HOST,
        port=DEFAULT_PORT,
        service_instance_id=f"dev-{uuid.uuid4()}",
        bootstrap_secret=create_bootstrap_secret(),
    )


def main() -> NoReturn:
    parser = argparse.ArgumentParser(description="Run the development service.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    arguments = parser.parse_args()
    LocalBindPolicy(host=arguments.host, port=arguments.port).validate()
    bootstrap_secret = create_bootstrap_secret()
    service_instance_id = f"dev-{uuid.uuid4()}"
    print(
        "Open the Vite UI with this one-time bootstrap fragment:\n"
        f"http://127.0.0.1:5173/#bootstrap_secret={bootstrap_secret}"
        f"&service_instance_id={service_instance_id}",
        flush=True,
    )
    import uvicorn

    uvicorn.run(
        create_app(
            production_config=development_runtime_config(),
            host=arguments.host,
            port=arguments.port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
        ),
        host=arguments.host,
        port=arguments.port,
    )
    raise SystemExit(0)


if __name__ == "__main__":
    main()
