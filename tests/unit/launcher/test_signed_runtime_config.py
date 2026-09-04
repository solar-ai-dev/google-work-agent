import hashlib
import io
import json
import shutil
from pathlib import Path

import pytest
from release.assemble_application_bundle import assemble_application_bundle
from tests.support.bundle_fixture import create_bundle_inputs

from google_work_agent.api.app import _run_installed_service, create_app
from google_work_agent.api.composition import (
    CoreInitializationError,
    ProductionRuntimeConfig,
    _load_installed_llm_runtime_selection,
    _load_verified_product_release_prompt_bundle,
    _VerifiedReleaseFile,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    SIGNED_PROMPT_MANIFEST_RELATIVE_PATH,
    default_prompt_manifest_path,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment
from google_work_agent.ports.llm.approved_model_manifest import (
    ApprovedModelEntryV1,
    ModelManifestV1,
)
from google_work_agent.ports.llm.local_model_product_decision import (
    LocalModelProductDecisionV1,
)
from google_work_agent.ports.llm.local_model_profile import (
    LocalInferenceClass,
    LocalModelProfileV1,
)
from release.profiles import DeploymentProfile


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
        "database_migration_version": "0001",
    }


def _release_files() -> list[dict[str, object]]:
    return [
        {
            "file_path": "service/GoogleWorkAgentService.exe",
            "file_size": 1,
            "sha256": "a" * 64,
        }
    ]


def test_service_composition__projects_closed__signed_launcher_handoff(tmp_path: Path) -> None:
    config = ProductionRuntimeConfig.from_signed_build_config(
        _signed_payload(),
        runtime_root=tmp_path / "data",
        working_directory=tmp_path / "install",
        verified_release_files=_release_files(),
        code_signature_verified_paths=["service/GoogleWorkAgentService.exe"],
    )

    assert config.release_version == "1.2.3"
    assert config.deployment_profile == "API_ONLY"
    assert config.oauth_environment is OAuthEnvironment.PRODUCTION
    assert config.oauth_client_id == "desktop-client-id"
    assert config.configuration_source == "SIGNED_RELEASE_MANIFEST"


def test_service_composition_rejects__unknown_or_secret__signed_handoff_field(
    tmp_path: Path,
) -> None:
    payload = _signed_payload()
    payload["client_secret"] = "forbidden"

    with pytest.raises(ValueError, match="schema is invalid"):
        ProductionRuntimeConfig.from_signed_build_config(
            payload,
            runtime_root=tmp_path / "data",
            working_directory=tmp_path / "install",
            verified_release_files=_release_files(),
            code_signature_verified_paths=["service/GoogleWorkAgentService.exe"],
        )


def test_local_capable__projects_only_release__verified_model_allowlist(
    tmp_path: Path,
) -> None:
    relative = "manifests/model-manifest-v1.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir(parents=True)
    manifest = ModelManifestV1(
        schema_version=1,
        minimum_ollama_version="0.6.0",
        approved_models=(
            ApprovedModelEntryV1("qwen3.5:4b", "a" * 63 + "b"),
            ApprovedModelEntryV1("qwen3.5:9b", "b" * 63 + "a"),
        ),
    )
    manifest_path.write_bytes(manifest.to_canonical_bytes() + b"\n")
    decision_relative = "manifests/local-model-product-decision-v1.json"
    decision_path = tmp_path / decision_relative
    decision = LocalModelProductDecisionV1(
        schema_version=1,
        decision_status="APPROVED_FOR_LOCAL_PROFILE",
        release_version="1.2.3",
        deployment_profile="LOCAL_CAPABLE",
        selected_model_id="qwen3.5:9b",
        model_manifest_hash=hashlib.sha256(manifest.to_canonical_bytes()).hexdigest(),
        candidate_config_hash=hashlib.sha256(b"candidate").hexdigest(),
        minimum_cpu_logical_cores=4,
        minimum_ram_bytes=8 * 1024**3,
        minimum_vram_bytes=4 * 1024**3,
        supported_os="WINDOWS",
        supported_architecture="AMD64",
    )
    decision_path.write_bytes(decision.to_canonical_bytes() + b"\n")
    profile_relative = "manifests/local-model-profile-v1.json"
    profile_path = tmp_path / profile_relative
    profile = LocalModelProfileV1(
        schema_version=1,
        profile_id="test-profile",
        runtime="OLLAMA",
        worker_model_id="qwen3.5:4b",
        reasoning_model_id="qwen3.5:9b",
        default_inference_class=LocalInferenceClass.REASONING,
        prompt_inference_classes=(),
    )
    profile_path.write_bytes(profile.to_canonical_bytes() + b"\n")
    release_files = {
        path: _VerifiedReleaseFile.from_payload(_release_row(tmp_path, path))
        for path in (relative, decision_relative, profile_relative)
    }

    selection = _load_installed_llm_runtime_selection(
        deployment_profile="LOCAL_CAPABLE",
        release_version="1.2.3",
        install_root=tmp_path,
        release_files=release_files,
    )

    assert selection.selected_model is not None
    assert selection.selected_model.digest == "b" * 63 + "a"
    assert selection.selected_model.minimum_runtime_version == "0.6.0"
    assert selection.local_model_profile == profile


def test_api_only__rejects_accidental__local_model_manifest(tmp_path: Path) -> None:
    relative = "manifests/model-manifest-v1.json"
    release_file = _VerifiedReleaseFile(
        file_path=relative,
        file_size=1,
        sha256="a" * 64,
    )

    with pytest.raises(CoreInitializationError, match="API_ONLY_LOCAL_RELEASE_ARTIFACT_FORBIDDEN"):
        _load_installed_llm_runtime_selection(
            deployment_profile="API_ONLY",
            release_version="1.2.3",
            install_root=tmp_path,
            release_files={relative: release_file},
        )


def test_signed_runtime__selects_verified_release_prompt__without_package_fallback(
    tmp_path: Path,
) -> None:
    inputs = create_bundle_inputs(tmp_path / "inputs")
    package_default_root = (
        inputs.service_distribution / "google_work_agent/application/prompt_runtime"
    )
    package_default_root.mkdir(parents=True)
    default_root = default_prompt_manifest_path().parent
    shutil.copy2(default_root / "prompt_manifest.json", package_default_root)
    shutil.copy2(default_root / "prompt_runtime_input_contract_v1.json", package_default_root)
    shutil.copytree(default_root / "sources", package_default_root / "sources")
    install_root = (tmp_path / "install").resolve()
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=inputs,
        output_root=install_root,
    )
    release_files = {
        path.relative_to(install_root).as_posix(): _VerifiedReleaseFile.from_payload(
            _release_row(install_root, path.relative_to(install_root).as_posix())
        )
        for path in install_root.rglob("*")
        if path.is_file()
    }

    selected = _load_verified_product_release_prompt_bundle(
        install_root=install_root,
        release_files=release_files,
    )

    assert selected == install_root / SIGNED_PROMPT_MANIFEST_RELATIVE_PATH
    assert selected.read_bytes() == inputs.prompt_manifest.read_bytes()
    package_default = (
        install_root / "service/google_work_agent/application/prompt_runtime/prompt_manifest.json"
    )
    assert selected.read_bytes() != package_default.read_bytes()

    without_selected = dict(release_files)
    without_selected.pop(SIGNED_PROMPT_MANIFEST_RELATIVE_PATH)
    with pytest.raises(CoreInitializationError, match="RELEASE_ARTIFACT_MISSING"):
        _load_verified_product_release_prompt_bundle(
            install_root=install_root,
            release_files=without_selected,
        )


def _release_row(root: Path, relative: str) -> dict[str, object]:
    content = (root / relative).read_bytes()
    return {
        "file_path": relative,
        "file_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_signed_deferred_app__serves_only_release__indexed_frontend_assets(
    tmp_path: Path,
) -> None:
    install = tmp_path / "install"
    (install / "frontend").mkdir(parents=True)
    (install / "frontend/index.html").write_text("<main>installed</main>", encoding="utf-8")
    (install / "frontend/unlisted.js").write_text("forbidden", encoding="utf-8")
    release_files = [_release_row(install, "frontend/index.html")]
    config = ProductionRuntimeConfig.from_signed_build_config(
        _signed_payload(),
        runtime_root=(tmp_path / "data").resolve(),
        working_directory=install.resolve(),
        verified_release_files=release_files,
        code_signature_verified_paths=[],
    )

    app = create_app(
        production_config=config,
        bootstrap_secret="one-time-secret",
        service_instance_id="instance-1",
    )
    site = config.verified_frontend_site()

    def route_paths(router: object) -> list[str]:
        paths: list[str] = []
        for route in router.routes:  # type: ignore[attr-defined]
            original = getattr(route, "original_router", None)
            if original is not None:
                paths.extend(route_paths(original))
            elif isinstance(getattr(route, "path", None), str):
                paths.append(route.path)
        return paths

    assert app.state.container.frontend_site is not None
    assert "/{path:path}" in route_paths(app.router)
    assert site is not None
    assert site.resolve_asset("unlisted.js") is None
    (install / "frontend/index.html").write_text("tampered", encoding="utf-8")
    assert site.resolve_asset("") is None


def test_installed_service_entrypoint__consumes_launcher_handoff__and_runs_uvicorn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install = tmp_path / "install"
    executable = install / "service/GoogleWorkAgentService.exe"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"service")
    (install / "frontend").mkdir()
    (install / "frontend/index.html").write_text("<main>installed</main>", encoding="utf-8")
    release_files = [
        _release_row(install, "frontend/index.html"),
        _release_row(install, "service/GoogleWorkAgentService.exe"),
    ]
    handoff = {
        "schema_version": 1,
        "service_instance_id": "instance-1",
        "bootstrap_secret": "one-time-secret",
        "signed_build_config": _signed_payload(),
        "verified_release_files": release_files,
        "code_signature_verified_paths": ["service/GoogleWorkAgentService.exe"],
    }
    ran: list[bool] = []
    monkeypatch.setattr("uvicorn.Server.run", lambda _server: ran.append(True))

    result = _run_installed_service(
        [
            "--host",
            "127.0.0.1",
            "--port",
            "43210",
            "--data-dir",
            str((tmp_path / "data").resolve()),
        ],
        input_stream=io.BytesIO(
            json.dumps(handoff, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        ),
        executable_path=executable,
    )

    assert result == 0
    assert ran == [True]


@pytest.mark.parametrize("port", ["0", "65536"])
def test_installed_service__entrypoint_rejects_out__of_range_port(port: str) -> None:
    assert (
        _run_installed_service(
            [
                "--host",
                "127.0.0.1",
                "--port",
                port,
                "--data-dir",
                str(Path.cwd().resolve()),
            ],
            input_stream=io.BytesIO(b""),
        )
        == 1
    )
