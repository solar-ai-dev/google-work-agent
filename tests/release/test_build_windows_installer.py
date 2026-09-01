from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from release.assemble_application_bundle import assemble_application_bundle
from release.build_windows_installer import build_windows_installer
from release.generate_release_manifest import ReleaseManifestParameters
from release.sign_release_artifacts import sign_release_artifacts

from release.profiles import DeploymentProfile
from tests.support.bundle_fixture import create_bundle_inputs


class _CodeSigner:
    def sign(self, artifact_path: Path, *, timestamp_url: str) -> None:
        artifact_path.write_bytes(artifact_path.read_bytes() + b"-signed")

    def verify(self, artifact_path: Path, *, require_timestamp: bool) -> bool:
        return require_timestamp and artifact_path.read_bytes().endswith(b"-signed")


class _ManifestSigner:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.from_private_bytes(bytes(reversed(range(32))))

    @property
    def public_key_pem(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    def sign(self, content: bytes) -> bytes:
        return self._key.sign(content)


class _InstallerBackend:
    def build(self, *, definition_path: Path, output_dir: Path) -> Path:
        script = definition_path.read_text(encoding="utf-8")
        assert "PrivilegesRequired=lowest" in script
        assert "API_ONLY" in script
        artifact = output_dir / "GoogleWorkAgent-1.2.3-API_ONLY-Setup.exe"
        artifact.write_bytes(b"installer")
        return artifact


def test_build_installer_consumes_verified_signed_profile_bundle(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    manifest_signer = _ManifestSigner()
    code_signer = _CodeSigner()
    code_artifacts = tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    )
    sign_release_artifacts(
        code_artifacts=code_artifacts,
        distribution_kind="PRODUCTION",
        code_signer=code_signer,
        timestamp_url="https://timestamp.example.test",
        bundle_root=bundle,
        manifest_parameters=ReleaseManifestParameters(
            app_version="1.2.3",
            build_channel="PRODUCTION",
            deployment_profile=DeploymentProfile.API_ONLY,
            oauth_env="PRODUCTION",
            oauth_client_id="desktop-client.apps.googleusercontent.com",
            api_contract_version="1",
            mcp_schema_version="2026-08-07.p0",
            policy_version="2026-08-06.p0",
            database_migration_version="0001",
        ),
        manifest_signer=manifest_signer,
        embedded_release_public_key_pem=manifest_signer.public_key_pem,
    )

    installer = build_windows_installer(
        bundle_root=bundle,
        output_dir=tmp_path / "installer",
        trusted_release_public_key_pem=manifest_signer.public_key_pem,
        backend=_InstallerBackend(),
        code_signature_verifier=code_signer,
    )
    sign_release_artifacts(
        code_artifacts=(installer,),
        distribution_kind="PRODUCTION",
        code_signer=code_signer,
        timestamp_url="https://timestamp.example.test",
    )

    assert installer.read_bytes().endswith(b"-signed")


def test_build_installer_rejects_file_added_after_manifest_signing(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    manifest_signer = _ManifestSigner()
    code_signer = _CodeSigner()
    code_artifacts = tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    )
    parameters = ReleaseManifestParameters(
        app_version="1.2.3",
        build_channel="PRODUCTION",
        deployment_profile=DeploymentProfile.API_ONLY,
        oauth_env="PRODUCTION",
        oauth_client_id="desktop-client.apps.googleusercontent.com",
        api_contract_version="1",
        mcp_schema_version="2026-08-07.p0",
        policy_version="2026-08-06.p0",
        database_migration_version="0001",
    )
    sign_release_artifacts(
        code_artifacts=code_artifacts,
        distribution_kind="PRODUCTION",
        code_signer=code_signer,
        timestamp_url="https://timestamp.example.test",
        bundle_root=bundle,
        manifest_parameters=parameters,
        manifest_signer=manifest_signer,
        embedded_release_public_key_pem=manifest_signer.public_key_pem,
    )
    (bundle / "runtime/override-config.json").write_text("{}", encoding="utf-8")

    with pytest.raises(RuntimeError, match="INSTALLATION_ARTIFACT_SET_MISMATCH"):
        build_windows_installer(
            bundle_root=bundle,
            output_dir=tmp_path / "installer",
            trusted_release_public_key_pem=manifest_signer.public_key_pem,
            backend=_InstallerBackend(),
            code_signature_verifier=code_signer,
        )
