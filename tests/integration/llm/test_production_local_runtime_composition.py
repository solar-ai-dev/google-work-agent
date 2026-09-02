from __future__ import annotations

import hashlib
import shutil
from dataclasses import replace
from pathlib import Path

import pytest
from tests.support.canonical_prompt_runtime import (
    activate_all_prompt_slots,
    copy_prompt_runtime_artifacts,
)
from tests.support.fakes import FakeAPIProviderTransport, FakeOllamaTransport

from google_work_agent.adapters.llm.runtime.evaluate_local_runtime_eligibility import (
    evaluate_local_runtime_eligibility,
)
from google_work_agent.api import composition
from google_work_agent.api.composition import (
    CoreInitializationError,
    DevelopmentConnectorBundle,
    _VerifiedReleaseFile,
)
from google_work_agent.api.container import ApiContainer
from google_work_agent.application.prompt_runtime.prompt_registry import PromptRegistry
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort
from google_work_agent.ports.llm.approved_model_manifest import (
    ApprovedModelEntryV1,
    ModelManifestV1,
)
from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)
from google_work_agent.ports.llm.runtime_selection import (
    LlmRuntimeSelectionV1,
    LocalRuntimeRequirementsV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import (
    ApprovedModelInfo,
    AvailabilityState,
    OutputSchemaDefinition,
    ProbeResult,
    ProviderResponsePayload,
)
from google_work_agent.ports.system.hardware_probe_port import HardwareProfileV1

MODEL_ID = "fixture-model:7b-q4"
MODEL_HASH = hashlib.sha256(b"fixture-model-content").hexdigest()
RELEASE_VERSION = "1.2.3-test"


class _MemorySecretStore(SecretStorePort):
    def __init__(self) -> None:
        self._values: dict[str, bytes] = {}

    def put(self, key: str, secret_bytes: bytes) -> None:
        self._values[key] = secret_bytes

    def get(self, key: str) -> bytes | None:
        return self._values.get(key)

    def delete(self, key: str) -> None:
        self._values.pop(key, None)


class _EligibleHardwareProbe:
    def __init__(self, **_kwargs: object) -> None:
        pass

    def probe(self) -> HardwareProfileV1:
        return HardwareProfileV1(
            1,
            8,
            16 * 1024**3,
            True,
            "fixture-gpu",
            8 * 1024**3,
            True,
            "0.6.2",
            True,
            "WINDOWS",
            "AMD64",
            (),
        )


def _write_local_release_artifacts(install_root: Path) -> tuple[Path, Path]:
    manifest = ModelManifestV1(
        schema_version=1,
        minimum_ollama_version="0.6.0",
        approved_models=(ApprovedModelEntryV1(MODEL_ID, MODEL_HASH),),
    )
    manifests = install_root / "manifests"
    manifests.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests / "model-manifest-v1.json"
    manifest_path.write_bytes(manifest.to_canonical_bytes() + b"\n")
    decision = LocalModelProductDecisionV1(
        schema_version=1,
        decision_status="APPROVED_FOR_LOCAL_PROFILE",
        release_version=RELEASE_VERSION,
        deployment_profile="LOCAL_CAPABLE",
        selected_model_id=MODEL_ID,
        model_manifest_hash=hashlib.sha256(manifest.to_canonical_bytes()).hexdigest(),
        candidate_config_hash=hashlib.sha256(b"fixture-candidate").hexdigest(),
        minimum_cpu_logical_cores=4,
        minimum_ram_bytes=8 * 1024**3,
        minimum_vram_bytes=4 * 1024**3,
        supported_os="WINDOWS",
        supported_architecture="AMD64",
    )
    decision_path = manifests / "local-model-product-decision-v1.json"
    decision_path.write_bytes(decision.to_canonical_bytes() + b"\n")
    return manifest_path, decision_path


def _release_file(install_root: Path, path: Path) -> _VerifiedReleaseFile:
    content = path.read_bytes()
    return _VerifiedReleaseFile(
        file_path=path.relative_to(install_root).as_posix(),
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )


def _write_signed_prompt_bundle(install_root: Path) -> tuple[Path, tuple[Path, ...]]:
    source_manifest, source_contract = copy_prompt_runtime_artifacts(
        install_root.parent / "prompt-source"
    )
    activate_all_prompt_slots(source_manifest)
    source_root = source_manifest.parent
    source_files = PromptRegistry(source_manifest, source_contract).product_release_bundle_files()
    target_root = install_root / "manifests/prompt"
    target_files: list[Path] = []
    for source in source_files:
        target = target_root / source.relative_to(source_root)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        target_files.append(target)
    return target_root / "prompt_manifest.json", tuple(target_files)


def _build_signed_container(
    *,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    release_files: tuple[_VerifiedReleaseFile, ...],
) -> ApiContainer:
    runtime_root = (tmp_path / "runtime").resolve()
    original_build_connectors = composition._build_connectors

    def build_external_connector_leaf(**kwargs: object) -> DevelopmentConnectorBundle:
        registry = composition.load_development_tool_registry()
        kwargs.update(
            configuration_source="EXPLICIT_DEVELOPMENT",
            verified_release_files=(),
            code_signature_verified_paths=frozenset(),
            development_tool_registry=registry,
            mcp_manifest_path=composition._write_mcp_manifest(runtime_root, registry),
            working_directory=Path(__file__).resolve().parents[3],
        )
        return original_build_connectors(**kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(composition, "_build_connectors", build_external_connector_leaf)
    return composition.build_production_runtime(
        runtime_root=runtime_root,
        working_directory=(tmp_path / "install").resolve(),
        mcp_manifest_version="2026-08-07.p0",
        bootstrap_secret="fixture-bootstrap-secret",
        release_version=RELEASE_VERSION,
        build_channel="TEST",
        deployment_profile="LOCAL_CAPABLE",
        oauth_environment=OAuthEnvironment.DEVELOPMENT,
        oauth_client_id="fixture-client-id",
        api_contract_version="1",
        policy_version="2026-08-06.p0",
        database_migration_version="0019",
        configuration_source="SIGNED_RELEASE_MANIFEST",
        service_instance_id="fixture-service",
        keyring_store=_MemorySecretStore(),
        verified_release_files=release_files,
    )


def test_signed_local_decision__production_composition__invokes_only_local_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    install_root = tmp_path / "install"
    prompt_manifest, prompt_files = _write_signed_prompt_bundle(install_root)
    frontend = install_root / "frontend" / "index.html"
    frontend.parent.mkdir(parents=True)
    frontend.write_text("<!doctype html>", encoding="utf-8")
    manifest_path, decision_path = _write_local_release_artifacts(install_root)
    release_files = tuple(
        _release_file(install_root, path)
        for path in (*prompt_files, frontend, manifest_path, decision_path)
    )
    monkeypatch.setattr(composition, "WindowsHardwareProbeAdapter", _EligibleHardwareProbe)
    local_transport = FakeOllamaTransport()
    local_transport.queued_payloads.append(
        ProviderResponsePayload(
            content={"answer": "local"},
            model=MODEL_ID,
            provider_request_id=None,
            input_tokens=3,
            output_tokens=1,
            latency_ms=2,
        )
    )
    api_transport = FakeAPIProviderTransport()
    monkeypatch.setattr(composition, "OllamaHTTPClient", lambda: local_transport)
    monkeypatch.setattr(composition, "GeminiHTTPClient", lambda: api_transport)

    container = _build_signed_container(
        monkeypatch=monkeypatch,
        tmp_path=tmp_path,
        release_files=release_files,
    )
    try:
        assert container.structured_inference_port is not None
        assert container.llm_runtime_selection is not None
        prompt_ref = PromptRegistry(
            prompt_manifest,
            prompt_manifest.parent / "prompt_runtime_input_contract_v1.json",
        ).lookup_by_id("planning.compose_answer")
        result = container.structured_inference_port.infer(
            "LOCAL_GPU",
            prompt_ref,
            {
                "user_request": "fixture",
                "request_intent": {},
                "answer_outline": {},
                "evidence": [],
            },
            OutputSchemaDefinition(
                "1",
                {
                    "type": "object",
                    "required": ["answer"],
                    "properties": {"answer": {"type": "string"}},
                    "additionalProperties": False,
                },
            ),
        )
        assert result.actual_runtime == "LOCAL_GPU"
        assert result.structured_output == {"answer": "local"}
        assert container.llm_runtime_selection.selected_model_id == MODEL_ID
        assert len([call for call in local_transport.invocations if call["kind"] == "invoke"]) == 1
        assert len([call for call in api_transport.invocations if call["kind"] == "invoke"]) == 0
    finally:
        for close in reversed(container.shutdown_callbacks):
            close()


@pytest.mark.parametrize(
    ("probe", "overrides", "expected_reason"),
    [
        (
            ProbeResult(AvailabilityState.UNAVAILABLE, "OLLAMA_UNAVAILABLE"),
            {},
            "OLLAMA_UNAVAILABLE",
        ),
        (ProbeResult(AvailabilityState.DEGRADED, "MODEL_NOT_FOUND"), {}, "MODEL_NOT_FOUND"),
        (ProbeResult(AvailabilityState.DEGRADED, "MODEL_HASH_MISMATCH"), {}, "MODEL_HASH_MISMATCH"),
        (
            ProbeResult(AvailabilityState.DEGRADED, "OLLAMA_VERSION_UNSUPPORTED"),
            {},
            "OLLAMA_VERSION_UNSUPPORTED",
        ),
        (ProbeResult(AvailabilityState.AVAILABLE), {"ram_total_bytes": 1}, "INSUFFICIENT_RAM"),
        (ProbeResult(AvailabilityState.AVAILABLE), {"vram_total_bytes": 1}, "INSUFFICIENT_VRAM"),
        (
            ProbeResult(AvailabilityState.AVAILABLE),
            {"operating_system": "LINUX"},
            "UNSUPPORTED_OPERATING_SYSTEM",
        ),
        (
            ProbeResult(AvailabilityState.AVAILABLE),
            {"architecture": "ARM64"},
            "UNSUPPORTED_ARCHITECTURE",
        ),
    ],
)
def test_local_eligibility__fails_closed__for_each_signed_requirement(
    probe: ProbeResult, overrides: dict[str, object], expected_reason: str
) -> None:
    model = ApprovedModelInfo(MODEL_ID, "OLLAMA", "1", "1", digest=MODEL_HASH)
    selection = _active_selection(model)
    values: dict[str, object] = {
        "runtime_selection": selection,
        "operating_system": "WINDOWS",
        "architecture": "AMD64",
        "cpu_logical_cores": 8,
        "ram_total_bytes": 16 * 1024**3,
        "gpu_present": True,
        "vram_total_bytes": 8 * 1024**3,
        "ollama_probe": probe,
    }
    values.update(overrides)
    decision = evaluate_local_runtime_eligibility(**values)  # type: ignore[arg-type]
    assert decision.eligible is False
    assert expected_reason in decision.safe_reason_codes


def _active_selection(model: ApprovedModelInfo) -> LlmRuntimeSelectionV1:
    from tests.support.llm_runtime import runtime_selection

    return replace(
        runtime_selection(deployment_profile="LOCAL_CAPABLE", model=model),
        requirements=LocalRuntimeRequirementsV1(
            minimum_cpu_logical_cores=4,
            minimum_ram_bytes=8 * 1024**3,
            minimum_vram_bytes=4 * 1024**3,
            supported_os="WINDOWS",
            supported_architecture="AMD64",
        ),
    )


@pytest.mark.parametrize(
    ("mutation", "expected_code"),
    [
        ("missing_manifest", "MODEL_MANIFEST_MISSING"),
        ("missing_decision", "PRODUCT_DECISION_MISSING"),
        ("manifest_hash", "PRODUCT_DECISION_MANIFEST_MISMATCH"),
        ("stale_decision", "PRODUCT_DECISION_STALE"),
        ("unapproved_model", "PRODUCT_DECISION_MODEL_NOT_APPROVED"),
    ],
)
def test_signed_local_release_artifact_failures__stop_before_composition__with_exact_code(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutation: str,
    expected_code: str,
) -> None:
    install_root = tmp_path / "install"
    _, prompt_files = _write_signed_prompt_bundle(install_root)
    frontend = install_root / "frontend" / "index.html"
    frontend.parent.mkdir(parents=True)
    frontend.write_text("<!doctype html>", encoding="utf-8")
    manifest_path, decision_path = _write_local_release_artifacts(install_root)
    if mutation in {"manifest_hash", "stale_decision", "unapproved_model"}:
        decision = LocalModelProductDecisionV1.from_bytes(decision_path.read_bytes())
        payload = {field: getattr(decision, field) for field in decision.__dataclass_fields__}
        if mutation == "manifest_hash":
            payload["model_manifest_hash"] = hashlib.sha256(b"stale-manifest").hexdigest()
        elif mutation == "stale_decision":
            payload["release_version"] = "older-release"
        else:
            payload["selected_model_id"] = "not-approved:1b"
        decision_path.write_bytes(
            LocalModelProductDecisionV1(**payload).to_canonical_bytes() + b"\n"
        )
    paths = [*prompt_files, frontend, manifest_path, decision_path]
    if mutation == "missing_manifest":
        paths.remove(manifest_path)
    if mutation == "missing_decision":
        paths.remove(decision_path)
    with pytest.raises(CoreInitializationError) as raised:
        _build_signed_container(
            monkeypatch=monkeypatch,
            tmp_path=tmp_path,
            release_files=tuple(_release_file(install_root, path) for path in paths),
        )
    assert raised.value.safe_code == expected_code
