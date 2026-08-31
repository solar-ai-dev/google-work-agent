from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from release.assemble_application_bundle import assemble_application_bundle
from release.generate_model_manifest import ApprovedModelEntryV1, generate_model_manifest

from release.profiles import DeploymentProfile
from tests.release.bundle_fixture import create_bundle_inputs


def test_api_only_bundle_materializes_exact_connector_tool_artifacts(tmp_path: Path) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    output = tmp_path / "bundle"

    paths = assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=inputs,
        output_root=output,
    )

    assert "manifests/model-manifest-v1.json" not in paths
    installed = json.loads(
        (output / "manifests/installed-connectors-v1.json").read_text(encoding="utf-8")
    )
    registry = json.loads(
        (output / "manifests/signed-tool-registry-v1.json").read_text(encoding="utf-8")
    )
    projection = json.loads(
        (
            output / "manifests/connectors/google_workspace/tool-descriptor-projection-v1.json"
        ).read_text(encoding="utf-8")
    )
    assert installed["connectors"][0]["connector_id"] == "google_workspace"
    assert {entry["tool_id"] for entry in projection["tools"]} == {
        entry["tool_id"] for entry in registry["entries"]
    }
    assert projection["registry_manifest_hash"] == registry["entries_hash"]
    assert not any(path.endswith((".py", ".pyc", ".map")) for path in paths)


def test_local_capable_bundle_requires_and_includes_generated_model_manifest(
    tmp_path: Path,
) -> None:
    model_manifest = tmp_path / "model-manifest-v1.json"
    generate_model_manifest(
        minimum_ollama_version="0.6.0",
        approved_models=(
            ApprovedModelEntryV1(
                "qwen2.5:7b-instruct-q4_K_M",
                hashlib.sha256(b"approved-model").hexdigest(),
            ),
        ),
        output_path=model_manifest,
    )
    inputs = create_bundle_inputs(tmp_path / "inputs", model_manifest=model_manifest)

    paths = assemble_application_bundle(
        profile=DeploymentProfile.LOCAL_CAPABLE,
        inputs=inputs,
        output_root=tmp_path / "bundle",
    )

    assert "manifests/model-manifest-v1.json" in paths
    assert not any("ollama.exe" in path.lower() for path in paths)


def test_bundle_rejects_sensitive_or_source_artifacts(tmp_path: Path) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    (inputs.frontend_distribution / ".env").write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden release artifact"):
        assemble_application_bundle(
            profile=DeploymentProfile.API_ONLY,
            inputs=inputs,
            output_root=tmp_path / "bundle",
        )


def test_local_capable_rejects_noncanonical_model_manifest(tmp_path: Path) -> None:
    model_manifest = tmp_path / "model-manifest-v1.json"
    model_manifest.write_text(
        '{"schema_version":1,"minimum_ollama_version":"0.6.0","approved_models":'
        '[{"model_id":"ambient-model","model_hash":"0"}]}',
        encoding="utf-8",
    )
    inputs = create_bundle_inputs(tmp_path / "inputs", model_manifest=model_manifest)

    with pytest.raises(ValueError, match="concrete lowercase"):
        assemble_application_bundle(
            profile=DeploymentProfile.LOCAL_CAPABLE,
            inputs=inputs,
            output_root=tmp_path / "bundle",
        )
