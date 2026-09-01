from __future__ import annotations

import json
from pathlib import Path

import pytest
from release.assemble_application_bundle import assemble_application_bundle
from release.generate_release_manifest import (
    ReleaseManifestParameters,
    generate_release_manifest,
)

from release.profiles import DeploymentProfile
from tests.support.bundle_fixture import create_bundle_inputs


def _parameters() -> ReleaseManifestParameters:
    return ReleaseManifestParameters(
        app_version="1.2.3",
        build_channel="DEVELOPMENT",
        deployment_profile=DeploymentProfile.API_ONLY,
        oauth_env="DEVELOPMENT",
        oauth_client_id="desktop-client.apps.googleusercontent.com",
        api_contract_version="1",
        mcp_schema_version="2026-08-07.p0",
        policy_version="2026-08-06.p0",
        database_migration_version="0001",
    )


def test_release_manifest_is_closed_sorted_and_deterministic(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )

    first = generate_release_manifest(bundle_root=bundle, parameters=_parameters())
    first_bytes = (bundle / "release-manifest.json").read_bytes()
    second = generate_release_manifest(bundle_root=bundle, parameters=_parameters())
    payload = json.loads(first_bytes)

    assert first == second
    assert (bundle / "release-manifest.json").read_bytes() == first_bytes
    assert set(payload) == {
        "schema_version",
        "app_version",
        "build_channel",
        "deployment_profile",
        "oauth_env",
        "oauth_client_id",
        "api_contract_version",
        "mcp_schema_version",
        "policy_version",
        "database_migration_version",
        "files",
    }
    paths = [entry["file_path"] for entry in payload["files"]]
    assert paths == sorted(paths)
    assert "release-manifest.json" not in paths
    assert "release-manifest.sig" not in paths
    assert all("\\" not in path and not Path(path).is_absolute() for path in paths)


def test_release_manifest_rejects_mcp_schema_different_from_installed_projection(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    parameters = _parameters()

    with pytest.raises(ValueError, match="MCP schema versions differ"):
        generate_release_manifest(
            bundle_root=bundle,
            parameters=ReleaseManifestParameters(
                app_version=parameters.app_version,
                build_channel=parameters.build_channel,
                deployment_profile=parameters.deployment_profile,
                oauth_env=parameters.oauth_env,
                oauth_client_id=parameters.oauth_client_id,
                api_contract_version=parameters.api_contract_version,
                mcp_schema_version="wrong-version",
                policy_version=parameters.policy_version,
                database_migration_version=parameters.database_migration_version,
            ),
        )
