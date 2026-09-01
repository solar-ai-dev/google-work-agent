import hashlib
import io
import json
from pathlib import Path

import pytest

from google_work_agent.api.app import _run_installed_service, create_app
from google_work_agent.api.composition import (
    CoreInitializationError,
    ProductionRuntimeConfig,
    _load_installed_approved_models,
    _VerifiedReleaseFile,
)
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


def test_service_composition_projects_closed_signed_launcher_handoff(tmp_path: Path) -> None:
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
            verified_release_files=_release_files(),
            code_signature_verified_paths=["service/GoogleWorkAgentService.exe"],
        )


def test_local_capable_projects_only_release_verified_model_allowlist(
    tmp_path: Path,
) -> None:
    relative = "manifests/model-manifest-v1.json"
    manifest_path = tmp_path / relative
    manifest_path.parent.mkdir(parents=True)
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "minimum_ollama_version": "0.6.0",
                "approved_models": [{"model_id": "qwen2.5:7b", "model_hash": "a" * 63 + "b"}],
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    content = manifest_path.read_bytes()
    release_file = _VerifiedReleaseFile(
        file_path=relative,
        file_size=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    models = _load_installed_approved_models(
        deployment_profile="LOCAL_CAPABLE",
        install_root=tmp_path,
        release_files={relative: release_file},
    )

    assert models["qwen2.5:7b"].digest == "a" * 63 + "b"
    assert models["qwen2.5:7b"].minimum_runtime_version == "0.6.0"


def test_api_only_rejects_accidental_local_model_manifest(tmp_path: Path) -> None:
    relative = "manifests/model-manifest-v1.json"
    release_file = _VerifiedReleaseFile(
        file_path=relative,
        file_size=1,
        sha256="a" * 64,
    )

    with pytest.raises(CoreInitializationError, match="API_ONLY_MODEL_MANIFEST_FORBIDDEN"):
        _load_installed_approved_models(
            deployment_profile="API_ONLY",
            install_root=tmp_path,
            release_files={relative: release_file},
        )


def _release_row(root: Path, relative: str) -> dict[str, object]:
    content = (root / relative).read_bytes()
    return {
        "file_path": relative,
        "file_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def test_signed_deferred_app_serves_only_release_indexed_frontend_assets(
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


def test_installed_service_entrypoint_consumes_launcher_handoff_and_runs_uvicorn(
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
def test_installed_service_entrypoint_rejects_out_of_range_port(port: str) -> None:
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
