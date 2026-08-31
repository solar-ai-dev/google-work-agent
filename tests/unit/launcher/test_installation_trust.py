from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from launcher.release_build_config import load_signed_build_config
from launcher.verify_installation import (
    InstallationVerificationError,
    verify_installation,
)


def _write_signed_installation(root: Path) -> bytes:
    service = root / "service" / "GoogleWorkAgentService.exe"
    frontend = root / "frontend" / "index.html"
    service.parent.mkdir(parents=True)
    frontend.parent.mkdir(parents=True)
    service.write_bytes(b"verified-service")
    frontend.write_bytes(b"verified-frontend")
    files = []
    for relative, path in (
        ("service/GoogleWorkAgentService.exe", service),
        ("frontend/index.html", frontend),
    ):
        content = path.read_bytes()
        files.append(
            {
                "file_path": relative,
                "file_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": 1,
        "app_version": "1.2.3",
        "build_channel": "STABLE",
        "deployment_profile": "LOCAL_CAPABLE",
        "oauth_env": "PRODUCTION",
        "oauth_client_id": "desktop-client-id",
        "api_contract_version": "1",
        "mcp_schema_version": "2026-08-07.p0",
        "policy_version": "2026-08-06.p0",
        "database_migration_version": "0018",
        "files": files,
    }
    manifest_bytes = json.dumps(
        manifest, sort_keys=True, separators=(",", ":")
    ).encode()
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    (root / "release-manifest.json").write_bytes(manifest_bytes)
    (root / "release-manifest.sig").write_text(
        base64.b64encode(private_key.sign(manifest_bytes)).decode("ascii"),
        encoding="ascii",
    )
    return private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


def test_signed_manifest_chain_projects_only_authenticated_build_fields(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)

    installation = verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)
    config = load_signed_build_config(installation)

    assert config.app_version == "1.2.3"
    assert config.deployment_profile == "LOCAL_CAPABLE"
    assert config.oauth_client_id == "desktop-client-id"
    assert {path.relative_to(tmp_path).as_posix() for path in installation.verified_files} == {
        "service/GoogleWorkAgentService.exe",
        "frontend/index.html",
    }
    assert "files" not in config.__dataclass_fields__
    assert "client_secret" not in config.__dataclass_fields__


def test_tampered_referenced_file_fails_closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    (tmp_path / "service" / "GoogleWorkAgentService.exe").write_bytes(b"tampered")

    with pytest.raises(InstallationVerificationError) as error:
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)

    assert error.value.safe_code == "INSTALLATION_FILE_TAMPERED"


def test_manifest_unknown_field_and_relative_install_root_fail_closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["client_secret"] = "forbidden"
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    manifest_path.write_bytes(content)
    (tmp_path / "release-manifest.sig").write_text(
        base64.b64encode(private_key.sign(content)).decode("ascii"), encoding="ascii"
    )

    with pytest.raises(InstallationVerificationError, match="MANIFEST_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)
    with pytest.raises(InstallationVerificationError, match="INSTALLATION_ROOT_INVALID"):
        verify_installation(Path("relative-install"), trusted_public_key_pem=public_key)


def test_missing_embedded_release_key_never_falls_back_to_unsigned_startup(
    tmp_path: Path,
) -> None:
    _write_signed_installation(tmp_path)

    with pytest.raises(InstallationVerificationError) as error:
        verify_installation(tmp_path.resolve())

    assert error.value.safe_code == "RELEASE_PUBLIC_KEY_UNAVAILABLE"
