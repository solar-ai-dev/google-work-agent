"""Test-only synchronous access to the canonical production composition entry."""

import secrets
from pathlib import Path

from google_work_agent.adapters.langgraph.profiles.profile_registry import GraphProfile
from google_work_agent.adapters.runtime.safe_mode import SafeModeController
from google_work_agent.api.composition import build_production_runtime
from google_work_agent.api.container import ApiContainer
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MCP_MANIFEST_VERSION = "2026-08-07.p0"


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
    graph_profile: GraphProfile = GraphProfile.SIX_ROLE_BASELINE,
) -> ApiContainer:
    return build_production_runtime(
        host=host,
        port=port,
        runtime_root=(runtime_root or PROJECT_ROOT / "runtime" / "development").resolve(),
        working_directory=PROJECT_ROOT,
        release_version="0.1.0-test",
        build_channel="TEST",
        deployment_profile="LOCAL_CAPABLE",
        oauth_environment=OAuthEnvironment.DEVELOPMENT,
        oauth_client_id="test-client-id",
        api_contract_version="1",
        mcp_manifest_version=MCP_MANIFEST_VERSION,
        policy_version="2026-08-06.p0",
        database_migration_version="development-latest",
        configuration_source="EXPLICIT_DEVELOPMENT",
        bootstrap_secret=bootstrap_secret or secrets.token_urlsafe(32),
        service_instance_id=service_instance_id,
        safe_mode_controller=safe_mode_controller,
        mcp_module_name=mcp_module_name,
        keyring_store=keyring_store,
        graph_profile=graph_profile,
    )


__all__ = ["build_test_production_container"]
