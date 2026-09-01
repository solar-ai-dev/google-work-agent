from __future__ import annotations

from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from launcher.verify_installation import InstallationVerificationError, verify_installation
from release.assemble_application_bundle import assemble_application_bundle
from release.generate_release_manifest import ReleaseManifestParameters
from release.sign_release_artifacts import sign_release_artifacts

from release.profiles import DeploymentProfile
from tests.support.bundle_fixture import create_bundle_inputs


class _CodeSigner:
    def sign(self, artifact_path: Path, *, timestamp_url: str) -> None:
        assert timestamp_url == "https://timestamp.example.test"
        artifact_path.write_bytes(artifact_path.read_bytes() + b"-signed")

    def verify(self, artifact_path: Path, *, require_timestamp: bool) -> bool:
        return require_timestamp and artifact_path.read_bytes().endswith(b"-signed")


class _ManifestSigner:
    def __init__(self) -> None:
        self._key = Ed25519PrivateKey.from_private_bytes(bytes(range(32)))

    @property
    def public_key_pem(self) -> bytes:
        return self._key.public_key().public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)

    def sign(self, content: bytes) -> bytes:
        return self._key.sign(content)


def _parameters() -> ReleaseManifestParameters:
    return ReleaseManifestParameters(
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


def _code_artifacts(bundle: Path) -> tuple[Path, ...]:
    return tuple(
        path
        for path in bundle.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    )


def test_signing_happens_before_manifest_hash_and_tampering_fails_closed(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    signer = _ManifestSigner()

    evidence = sign_release_artifacts(
        code_artifacts=_code_artifacts(bundle),
        distribution_kind="PRODUCTION",
        code_signer=_CodeSigner(),
        timestamp_url="https://timestamp.example.test",
        bundle_root=bundle,
        manifest_parameters=_parameters(),
        manifest_signer=signer,
        embedded_release_public_key_pem=signer.public_key_pem,
    )

    assert evidence.manifest_path == bundle / "release-manifest.json"
    assert evidence.manifest_signature_path == bundle / "release-manifest.sig"
    installation = verify_installation(
        bundle.resolve(),
        trusted_public_key_pem=signer.public_key_pem,
        code_signature_verifier=lambda _path: True,
    )
    assert len(installation.verified_files) > 5
    (bundle / "service/GoogleWorkAgentService.exe").write_bytes(b"post-sign mutation")
    with pytest.raises(InstallationVerificationError, match="INSTALLATION_FILE_TAMPERED"):
        verify_installation(bundle.resolve(), trusted_public_key_pem=signer.public_key_pem)


def test_production_rejects_unsigned_or_incomplete_code_artifact_set(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    assemble_application_bundle(
        profile=DeploymentProfile.API_ONLY,
        inputs=create_bundle_inputs(tmp_path / "inputs"),
        output_root=bundle,
    )
    with pytest.raises(ValueError, match="require code signing"):
        sign_release_artifacts(
            code_artifacts=_code_artifacts(bundle),
            distribution_kind="PRODUCTION",
            code_signer=None,
            timestamp_url=None,
        )
    with pytest.raises(ValueError, match="artifact set mismatch"):
        sign_release_artifacts(
            code_artifacts=_code_artifacts(bundle)[:-1],
            distribution_kind="PRODUCTION",
            code_signer=_CodeSigner(),
            timestamp_url="https://timestamp.example.test",
            bundle_root=bundle,
            manifest_parameters=_parameters(),
            manifest_signer=_ManifestSigner(),
            embedded_release_public_key_pem=_ManifestSigner().public_key_pem,
        )
