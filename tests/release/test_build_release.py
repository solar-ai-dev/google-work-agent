from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pytest
from release.assemble_application_bundle import ApplicationBundleInputs
from release.generate_local_model_product_decision import (
    generate_local_model_product_decision,
)
from release.generate_model_manifest import ApprovedModelEntryV1, generate_model_manifest
from scripts import build_release

from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)
from release.profiles import DeploymentProfile
from tests.support.bundle_fixture import create_bundle_inputs

MODEL_ID = "qwen2.5:7b-instruct-q4_K_M"


@dataclass
class _ExternalLeafCalls:
    signing: int = 0
    installer: int = 0


class _ManifestSigner:
    def __init__(self, _path: Path, _password: bytes | None) -> None:
        pass


def _install_external_leaf_fakes(
    monkeypatch: pytest.MonkeyPatch,
) -> _ExternalLeafCalls:
    calls = _ExternalLeafCalls()

    def sign_release_artifacts(**_kwargs: object) -> None:
        calls.signing += 1

    def build_windows_installer(**kwargs: object) -> Path:
        calls.installer += 1
        output_dir = kwargs["output_dir"]
        assert isinstance(output_dir, Path)
        output_dir.mkdir(parents=True, exist_ok=True)
        installer = output_dir / "GoogleWorkAgent-test-Setup.exe"
        installer.write_bytes(b"installer")
        return installer

    monkeypatch.setattr(build_release, "Ed25519PemManifestSigner", _ManifestSigner)
    monkeypatch.setattr(build_release, "sign_release_artifacts", sign_release_artifacts)
    monkeypatch.setattr(build_release, "discover_inno_setup_backend", object)
    monkeypatch.setattr(build_release, "build_windows_installer", build_windows_installer)
    return calls


def _local_artifacts(
    root: Path,
    *,
    decision_manifest_hash: str | None = None,
) -> tuple[Path, Path]:
    manifest_path = root / "model-manifest-v1.json"
    manifest = generate_model_manifest(
        minimum_ollama_version="0.6.0",
        approved_models=(
            ApprovedModelEntryV1(
                MODEL_ID,
                hashlib.sha256(b"approved-model").hexdigest(),
            ),
        ),
        output_path=manifest_path,
    )
    decision_path = root / "local-model-product-decision-v1.json"
    generate_local_model_product_decision(
        decision=LocalModelProductDecisionV1(
            schema_version=1,
            decision_status="APPROVED_FOR_LOCAL_PROFILE",
            release_version="test-release",
            deployment_profile="LOCAL_CAPABLE",
            selected_model_id=MODEL_ID,
            model_manifest_hash=(
                decision_manifest_hash
                if decision_manifest_hash is not None
                else hashlib.sha256(manifest.to_canonical_bytes()).hexdigest()
            ),
            candidate_config_hash=hashlib.sha256(b"candidate-config").hexdigest(),
            minimum_cpu_logical_cores=4,
            minimum_ram_bytes=8 * 1024**3,
            minimum_vram_bytes=4 * 1024**3,
            supported_os="WINDOWS",
            supported_architecture="AMD64",
        ),
        output_path=decision_path,
    )
    return manifest_path, decision_path


def _arguments(
    root: Path,
    *,
    profile: DeploymentProfile,
    model_manifest: Path | None = None,
    product_decision: Path | None = None,
) -> list[str]:
    inputs = create_bundle_inputs(root / "inputs")
    private_key = root / "manifest-private-key.pem"
    private_key.write_text("test-only", encoding="utf-8")
    arguments = [
        "--profile",
        profile.value,
        "--output-dir",
        str(root / "bundle"),
        "--launcher-dist",
        str(inputs.launcher_distribution),
        "--service-dist",
        str(inputs.service_distribution),
        "--frontend-dist",
        str(inputs.frontend_distribution),
        "--mcp-dist",
        str(inputs.mcp_distribution),
        "--runtime-dist",
        str(inputs.runtime_distribution),
        "--schemas-dir",
        str(inputs.schemas),
        "--migrations-dir",
        str(inputs.migrations),
        "--uninstaller-dist",
        str(inputs.uninstaller_distribution),
        "--installed-connector-manifest",
        str(inputs.installed_connector_manifest),
        "--signed-tool-registry",
        str(inputs.signed_tool_registry),
        "--app-version",
        "test-release",
        "--build-channel",
        "DEVELOPMENT",
        "--oauth-env",
        "DEVELOPMENT",
        "--oauth-client-id",
        "test-client-id",
        "--api-contract-version",
        "1",
        "--mcp-schema-version",
        "2026-08-07.p0",
        "--policy-version",
        "2026-08-06.p0",
        "--database-migration-version",
        "0019",
        "--manifest-private-key",
        str(private_key),
        "--installer-output-dir",
        str(root / "installer"),
    ]
    if model_manifest is not None:
        arguments.extend(("--model-manifest", str(model_manifest)))
    if product_decision is not None:
        arguments.extend(("--local-model-product-decision", str(product_decision)))
    return arguments


def test_local_capable_cli__forwards_exact_local_paths__into_canonical_assembler(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_manifest, product_decision = _local_artifacts(tmp_path)
    _install_external_leaf_fakes(monkeypatch)
    canonical_assembler = build_release.assemble_application_bundle
    observed: list[ApplicationBundleInputs] = []

    def recording_assembler(**kwargs: object) -> tuple[str, ...]:
        inputs = kwargs["inputs"]
        assert isinstance(inputs, ApplicationBundleInputs)
        observed.append(inputs)
        return canonical_assembler(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(build_release, "assemble_application_bundle", recording_assembler)

    assert (
        build_release.main(
            _arguments(
                tmp_path,
                profile=DeploymentProfile.LOCAL_CAPABLE,
                model_manifest=model_manifest,
                product_decision=product_decision,
            )
        )
        == 0
    )
    assert len(observed) == 1
    assert observed[0].model_manifest == model_manifest.resolve()
    assert observed[0].local_model_product_decision == product_decision.resolve()


def test_local_capable_cli__valid_artifacts__complete_release_pipeline(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_manifest, product_decision = _local_artifacts(tmp_path)
    calls = _install_external_leaf_fakes(monkeypatch)

    assert (
        build_release.main(
            _arguments(
                tmp_path,
                profile=DeploymentProfile.LOCAL_CAPABLE,
                model_manifest=model_manifest,
                product_decision=product_decision,
            )
        )
        == 0
    )
    assert (tmp_path / "bundle/manifests/model-manifest-v1.json").is_file()
    assert (tmp_path / "bundle/manifests/local-model-product-decision-v1.json").is_file()
    assert calls.signing == 2
    assert calls.installer == 1


@pytest.mark.parametrize("missing", ["model_manifest", "product_decision"])
def test_local_capable_cli__missing_local_artifact__fails_before_external_leaves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    missing: str,
) -> None:
    model_manifest, product_decision = _local_artifacts(tmp_path)
    calls = _install_external_leaf_fakes(monkeypatch)

    with pytest.raises(ValueError, match="LOCAL_CAPABLE requires"):
        build_release.main(
            _arguments(
                tmp_path,
                profile=DeploymentProfile.LOCAL_CAPABLE,
                model_manifest=None if missing == "model_manifest" else model_manifest,
                product_decision=None if missing == "product_decision" else product_decision,
            )
        )
    assert calls.signing == 0
    assert calls.installer == 0


@pytest.mark.parametrize("artifact", ["model_manifest", "product_decision"])
def test_api_only_cli__with_local_artifact__fails_before_external_leaves(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    artifact: str,
) -> None:
    model_manifest, product_decision = _local_artifacts(tmp_path)
    calls = _install_external_leaf_fakes(monkeypatch)

    with pytest.raises(ValueError, match="API_ONLY must not receive local model"):
        build_release.main(
            _arguments(
                tmp_path,
                profile=DeploymentProfile.API_ONLY,
                model_manifest=model_manifest if artifact == "model_manifest" else None,
                product_decision=(
                    product_decision if artifact == "product_decision" else None
                ),
            )
        )
    assert calls.signing == 0
    assert calls.installer == 0


def test_local_capable_cli__mismatched_artifacts__surfaces_assembler_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    model_manifest, product_decision = _local_artifacts(
        tmp_path,
        decision_manifest_hash=hashlib.sha256(b"different-manifest").hexdigest(),
    )
    calls = _install_external_leaf_fakes(monkeypatch)

    with pytest.raises(ValueError, match="product decision manifest hash mismatch"):
        build_release.main(
            _arguments(
                tmp_path,
                profile=DeploymentProfile.LOCAL_CAPABLE,
                model_manifest=model_manifest,
                product_decision=product_decision,
            )
        )
    assert calls.signing == 0
    assert calls.installer == 0
