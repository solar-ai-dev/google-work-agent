from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key as generate_rsa_key
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat, load_pem_public_key
from launcher.release_build_config import load_signed_build_config
from launcher.verify_installation import (
    EMBEDDED_RELEASE_PUBLIC_KEY_PEM,
    EMBEDDED_RELEASE_PUBLIC_KEY_SHA256,
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
    for relative, path in sorted(
        (
            ("service/GoogleWorkAgentService.exe", service),
            ("frontend/index.html", frontend),
        )
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
        "database_migration_version": "0001",
        "files": files,
    }
    manifest_bytes = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    private_key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))
    (root / "release-manifest.json").write_bytes(manifest_bytes)
    (root / "release-manifest.sig").write_text(
        base64.b64encode(private_key.sign(manifest_bytes)).decode("ascii"),
        encoding="ascii",
    )
    return private_key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)


def _test_private_key() -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(bytes(range(32)))


def _write_signature(root: Path, content: bytes) -> None:
    (root / "release-manifest.sig").write_text(
        base64.b64encode(_test_private_key().sign(content)).decode("ascii"),
        encoding="ascii",
    )


def test_signed_manifest__chain_projects_only__authenticated_build_fields(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)

    installation = verify_installation(
        tmp_path.resolve(),
        trusted_public_key_pem=public_key,
        code_signature_verifier=lambda _path: True,
    )
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


def test_tampered_referenced__file_fails__closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    (tmp_path / "service" / "GoogleWorkAgentService.exe").write_bytes(b"tampered")

    with pytest.raises(InstallationVerificationError) as error:
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)

    assert error.value.safe_code == "INSTALLATION_FILE_TAMPERED"


def test_manifest_unknown_field__and_relative_install__root_fail_closed(tmp_path: Path) -> None:
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


def test_explicitly_missing_release__key_never_falls__back_to_unsigned_startup(
    tmp_path: Path,
) -> None:
    _write_signed_installation(tmp_path)

    with pytest.raises(InstallationVerificationError) as error:
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=None)

    assert error.value.safe_code == "RELEASE_PUBLIC_KEY_UNAVAILABLE"


def test_production_release__public_key_is__embedded_and_fingerprinted() -> None:
    assert isinstance(load_pem_public_key(EMBEDDED_RELEASE_PUBLIC_KEY_PEM), Ed25519PublicKey)
    assert hashlib.sha256(EMBEDDED_RELEASE_PUBLIC_KEY_PEM).hexdigest() == (
        EMBEDDED_RELEASE_PUBLIC_KEY_SHA256
    )


def test_manifest_one__byte_mutation__fails_signature_verification(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    content = bytearray(manifest_path.read_bytes())
    content[0] ^= 1
    manifest_path.write_bytes(content)

    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)


def test_signature_one__byte_mutation__fails_closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    signature_path = tmp_path / "release-manifest.sig"
    signature = bytearray(base64.b64decode(signature_path.read_text(encoding="ascii")))
    signature[0] ^= 1
    signature_path.write_text(base64.b64encode(signature).decode("ascii"), encoding="ascii")

    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)


def test_wrong_public__key_fails__closed(tmp_path: Path) -> None:
    _write_signed_installation(tmp_path)
    wrong_public_key = Ed25519PrivateKey.generate().public_key().public_bytes(
        Encoding.PEM,
        PublicFormat.SubjectPublicKeyInfo,
    )

    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=wrong_public_key)


def test_unsupported_public__key_algorithm__fails_closed(tmp_path: Path) -> None:
    _write_signed_installation(tmp_path)
    rsa_public_key = (
        generate_rsa_key(public_exponent=65537, key_size=2048)
        .public_key()
        .public_bytes(
            Encoding.PEM,
            PublicFormat.SubjectPublicKeyInfo,
        )
    )

    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=rsa_public_key)


def test_missing_or__malformed_signature__fails_closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    signature_path = tmp_path / "release-manifest.sig"
    signature_path.unlink()
    with pytest.raises(InstallationVerificationError, match="MANIFEST_MISSING"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)

    signature_path.write_text("not-base64", encoding="ascii")
    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)


def test_signed_digest__mismatch_fails__closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    manifest_path = tmp_path / "release-manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["files"][0]["sha256"] = "0" * 64
    content = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    manifest_path.write_bytes(content)
    _write_signature(tmp_path, content)

    with pytest.raises(InstallationVerificationError, match="INSTALLATION_FILE_TAMPERED"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)


def test_signed_malformed__manifest_fails__closed(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    content = b"{malformed"
    (tmp_path / "release-manifest.json").write_bytes(content)
    _write_signature(tmp_path, content)

    with pytest.raises(InstallationVerificationError, match="MANIFEST_INVALID"):
        verify_installation(tmp_path.resolve(), trusted_public_key_pem=public_key)


def test_test_only_key__cannot_authenticate_against__production_trust_root(
    tmp_path: Path,
) -> None:
    _write_signed_installation(tmp_path)

    with pytest.raises(InstallationVerificationError, match="SIGNATURE_INVALID"):
        verify_installation(tmp_path.resolve())


def test_unlisted_runtime__override_fails__before_code_execution(tmp_path: Path) -> None:
    public_key = _write_signed_installation(tmp_path)
    override = tmp_path / "runtime" / "override-config.json"
    override.parent.mkdir()
    override.write_text("{}", encoding="utf-8")

    with pytest.raises(
        InstallationVerificationError,
        match="INSTALLATION_ARTIFACT_SET_MISMATCH",
    ):
        verify_installation(
            tmp_path.resolve(),
            trusted_public_key_pem=public_key,
            code_signature_verifier=lambda _path: True,
        )


def test_invalid_authenticode__fails_closed__after_manifest_verification(
    tmp_path: Path,
) -> None:
    public_key = _write_signed_installation(tmp_path)

    with pytest.raises(
        InstallationVerificationError,
        match="INSTALLATION_CODE_SIGNATURE_INVALID",
    ):
        verify_installation(
            tmp_path.resolve(),
            trusted_public_key_pem=public_key,
            code_signature_verifier=lambda _path: False,
        )


def test_exact_installer__generated_uninstaller_pair__requires_code_signature(
    tmp_path: Path,
) -> None:
    public_key = _write_signed_installation(tmp_path)
    (tmp_path / "unins000.exe").write_bytes(b"signed-uninstaller")
    (tmp_path / "unins000.dat").write_bytes(b"uninstall-metadata")
    verified_paths: list[Path] = []

    def verify_code_signature(path: Path) -> bool:
        verified_paths.append(path)
        return True

    installation = verify_installation(
        tmp_path.resolve(),
        trusted_public_key_pem=public_key,
        code_signature_verifier=verify_code_signature,
    )

    assert tmp_path / "unins000.exe" in installation.code_signature_verified_files
    assert tmp_path / "unins000.exe" in verified_paths
