from pathlib import Path

import pytest

from google_work_agent.api.composition import ProductionRuntimeConfig
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment


def _signed_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "app_version": "1.2.3",
        "build_channel": "STABLE",
        "deployment_profile": "API_ONLY",
        "oauth_env": "PRODUCTION",
        "oauth_client_id": "desktop-client-id",
        "api_contract_version": "1",
        "mcp_schema_version": "2026-08-07.p0",
        "policy_version": "2026-08-06.p0",
        "database_migration_version": "0018",
    }


def test_service_composition_projects_closed_signed_launcher_handoff(tmp_path: Path) -> None:
    config = ProductionRuntimeConfig.from_signed_build_config(
        _signed_payload(),
        runtime_root=tmp_path / "data",
        working_directory=tmp_path / "install",
    )

    assert config.release_version == "1.2.3"
    assert config.deployment_profile == "API_ONLY"
    assert config.oauth_environment is OAuthEnvironment.PRODUCTION
    assert config.oauth_client_id == "desktop-client-id"
    assert config.configuration_source == "SIGNED_RELEASE_MANIFEST"


def test_service_composition_rejects_unknown_or_secret_signed_handoff_field(
    tmp_path: Path,
) -> None:
    payload = _signed_payload()
    payload["client_secret"] = "forbidden"

    with pytest.raises(ValueError, match="schema is invalid"):
        ProductionRuntimeConfig.from_signed_build_config(
            payload,
            runtime_root=tmp_path / "data",
            working_directory=tmp_path / "install",
        )
