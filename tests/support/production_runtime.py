"""Test-only synchronous access to the canonical production composition entry."""

from pathlib import Path

from google_work_agent.adapters.runtime import SafeModeController
from google_work_agent.api.composition import build_production_runtime
from google_work_agent.api.container import ApiContainer
from google_work_agent.launcher.bootstrap_secret import create_bootstrap_secret
from google_work_agent.launcher.development_constants import (
    MCP_MANIFEST_VERSION,
    PROJECT_ROOT,
)
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort


def build_test_production_container(
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
    runtime_root: Path | None = None,
    bootstrap_secret: str | None = None,
    service_instance_id: str | None = None,
    safe_mode_controller: SafeModeController | None = None,
    mcp_module_name: str | None = None,
    keyring_store: SecretStorePort | None = None,
) -> ApiContainer:
    return build_production_runtime(
        host=host,
        port=port,
        runtime_root=(runtime_root or PROJECT_ROOT / "runtime" / "development").resolve(),
        working_directory=PROJECT_ROOT,
        mcp_manifest_version=MCP_MANIFEST_VERSION,
        bootstrap_secret=bootstrap_secret or create_bootstrap_secret(),
        service_instance_id=service_instance_id,
        safe_mode_controller=safe_mode_controller,
        mcp_module_name=mcp_module_name,
        keyring_store=keyring_store,
    )


__all__ = ["build_test_production_container"]
