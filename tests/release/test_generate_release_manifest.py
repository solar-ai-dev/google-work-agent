from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from release.assemble_application_bundle import assemble_application_bundle
from release.generate_release_manifest import (
    ReleaseManifestParameters,
    generate_release_manifest,
)

from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
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


def test_release_manifest__is_closed__sorted_and_deterministic(tmp_path: Path) -> None:
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
    rows = {entry["file_path"]: entry for entry in payload["files"]}
    prompt_root = bundle / "manifests/prompt"
    registry = PromptRegistry(
        prompt_root / "prompt_manifest.json",
        prompt_root / "prompt_runtime_input_contract_v1.json",
    )
    expected_prompt_paths = {
        path.relative_to(bundle).as_posix() for path in registry.product_release_bundle_files()
    }
    assert expected_prompt_paths <= rows.keys()
    for relative in expected_prompt_paths:
        content = (bundle / relative).read_bytes()
        assert rows[relative]["sha256"] == hashlib.sha256(content).hexdigest()


@pytest.mark.parametrize(
    ("relative", "replacement", "message"),
    [
        ("prompt_manifest.json", b"{}", "prompt manifest fields mismatch"),
        (
            "prompt_runtime_input_contract_v1.json",
            b"{}",
            "fields mismatch",
        ),
        (
            "sources/planning.compose_answer.md",
            b"tampered source",
            "Prompt source hash mismatch",
        ),
        (
            "activation-evidence/planning.compose_answer/dataset.json",
            b"tampered evidence",
            "artifact hash mismatch",
        ),
    ],
)
def test_release_manifest__rejects_materialized_prompt__artifact_tamper(
    tmp_path: Path,
    relative: str,
    replacement: bytes,
    message: str,
) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    (bundle / "manifests/prompt" / relative).write_bytes(replacement)

    with pytest.raises((ValueError, RuntimeError), match=message):
        generate_release_manifest(bundle_root=bundle, parameters=_parameters())


def test_release_manifest_rejects__mcp_schema_different__from_installed_projection(
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
