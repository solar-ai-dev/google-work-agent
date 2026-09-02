from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from release.assemble_application_bundle import assemble_application_bundle
from release.generate_local_model_product_decision import (
    generate_local_model_product_decision,
)
from release.generate_model_manifest import ApprovedModelEntryV1, generate_model_manifest

from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)
from release.profiles import DeploymentProfile
from tests.support.bundle_fixture import create_bundle_inputs
from tests.support.canonical_prompt_runtime import deactivate_prompt_slot


def test_api_only__bundle_materializes_exact__connector_tool_artifacts(tmp_path: Path) -> None:
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
    assert projection["manifest_version"] == "2026-08-07.p0"
    assert projection["protocol_version"] == "2026-08-07.p0"
    assert not any(path.endswith((".py", ".pyc", ".map")) for path in paths)


def test_local_capable_bundle__requires_and_includes__generated_model_manifest(
    tmp_path: Path,
) -> None:
    model_manifest = tmp_path / "model-manifest-v1.json"
    manifest = generate_model_manifest(
        minimum_ollama_version="0.6.0",
        approved_models=(
            ApprovedModelEntryV1(
                "qwen2.5:7b-instruct-q4_K_M",
                hashlib.sha256(b"approved-model").hexdigest(),
            ),
        ),
        output_path=model_manifest,
    )
    decision_path = tmp_path / "local-model-product-decision-v1.json"
    generate_local_model_product_decision(
        decision=LocalModelProductDecisionV1(
            schema_version=1,
            decision_status="APPROVED_FOR_LOCAL_PROFILE",
            release_version="test-release",
            deployment_profile="LOCAL_CAPABLE",
            selected_model_id="qwen2.5:7b-instruct-q4_K_M",
            model_manifest_hash=hashlib.sha256(manifest.to_canonical_bytes()).hexdigest(),
            candidate_config_hash=hashlib.sha256(b"candidate-config").hexdigest(),
            minimum_cpu_logical_cores=4,
            minimum_ram_bytes=8 * 1024**3,
            minimum_vram_bytes=4 * 1024**3,
            supported_os="WINDOWS",
            supported_architecture="AMD64",
        ),
        output_path=decision_path,
    )
    inputs = create_bundle_inputs(
        tmp_path / "inputs",
        model_manifest=model_manifest,
        local_model_product_decision=decision_path,
    )

    paths = assemble_application_bundle(
        profile=DeploymentProfile.LOCAL_CAPABLE,
        inputs=inputs,
        output_root=tmp_path / "bundle",
    )

    assert "manifests/model-manifest-v1.json" in paths
    assert "manifests/local-model-product-decision-v1.json" in paths
    assert not any("ollama.exe" in path.lower() for path in paths)


def test_bundle_rejects__sensitive_or__source_artifacts(tmp_path: Path) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    (inputs.frontend_distribution / ".env").write_text("SECRET=value", encoding="utf-8")

    with pytest.raises(ValueError, match="forbidden release artifact"):
        assemble_application_bundle(
            profile=DeploymentProfile.API_ONLY,
            inputs=inputs,
            output_root=tmp_path / "bundle",
        )


def test_signed_bundle__rejects_draft__prompt_baseline(tmp_path: Path) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    deactivate_prompt_slot(inputs.prompt_manifest, "planning.compose_answer")

    with pytest.raises(RuntimeError, match="DRAFT"):
        assemble_application_bundle(
            profile=DeploymentProfile.API_ONLY,
            inputs=inputs,
            output_root=tmp_path / "bundle",
        )


def test_signed_bundle__materializes_exact_validated__prompt_file_closure(
    tmp_path: Path,
) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    unreferenced = inputs.prompt_manifest.parent / "unreferenced.txt"
    unreferenced.write_text("not part of the Prompt bundle closure", encoding="utf-8")
    output = tmp_path / "bundle"

    paths = assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=inputs,
        output_root=output,
    )

    prompt_root = output / "manifests/prompt"
    assert (prompt_root / "prompt_manifest.json").read_bytes() == (
        inputs.prompt_manifest.read_bytes()
    )
    assert (prompt_root / "prompt_runtime_input_contract_v1.json").is_file()
    assert len(tuple((prompt_root / "sources").glob("*.md"))) == 21
    assert len(tuple((prompt_root / "activation-evidence").rglob("*.json"))) == 126
    assert "manifests/prompt/unreferenced.txt" not in paths


def test_local_capable__rejects_noncanonical__model_manifest(tmp_path: Path) -> None:
    model_manifest = tmp_path / "model-manifest-v1.json"
    model_manifest.write_text(
        '{"schema_version":1,"minimum_ollama_version":"0.6.0","approved_models":'
        '[{"model_id":"ambient-model","model_hash":"0"}]}',
        encoding="utf-8",
    )
    decision_path = tmp_path / "local-model-product-decision-v1.json"
    decision_path.write_text("{}", encoding="utf-8")
    inputs = create_bundle_inputs(
        tmp_path / "inputs",
        model_manifest=model_manifest,
        local_model_product_decision=decision_path,
    )

    with pytest.raises(ValueError, match="concrete lowercase"):
        assemble_application_bundle(
            profile=DeploymentProfile.LOCAL_CAPABLE,
            inputs=inputs,
            output_root=tmp_path / "bundle",
        )
