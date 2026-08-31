"""Apply canonical Windows code signing, timestamping, and manifest signing."""

from __future__ import annotations

import base64
import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    PublicFormat,
    load_pem_private_key,
)

from release.generate_release_manifest import (
    ReleaseManifestParameters,
    generate_release_manifest,
)

type DistributionKind = Literal["DEVELOPMENT", "STAGING", "PRODUCTION"]


class CodeSigningBackend(Protocol):
    def sign(self, artifact_path: Path, *, timestamp_url: str) -> None: ...

    def verify(self, artifact_path: Path, *, require_timestamp: bool) -> bool: ...


class DetachedManifestSigner(Protocol):
    @property
    def public_key_pem(self) -> bytes: ...

    def sign(self, content: bytes) -> bytes: ...


@dataclass(frozen=True, slots=True)
class SigningEvidence:
    signed_code_artifacts: tuple[Path, ...]
    manifest_path: Path | None
    manifest_signature_path: Path | None
    release_public_key_sha256: str | None
    timestamp_url: str | None


@dataclass(frozen=True, slots=True)
class WindowsSignToolBackend:
    """Production Authenticode backend with external certificate selection."""

    signtool_path: Path
    certificate_selector: tuple[str, ...] = field(repr=False)

    def sign(self, artifact_path: Path, *, timestamp_url: str) -> None:
        if not self.signtool_path.is_file():
            raise FileNotFoundError("signtool executable is unavailable")
        if not self.certificate_selector:
            raise ValueError("an external certificate selector is required")
        command = (
            str(self.signtool_path),
            "sign",
            "/fd",
            "SHA256",
            "/td",
            "SHA256",
            "/tr",
            timestamp_url,
            *self.certificate_selector,
            str(artifact_path),
        )
        _run_sign_tool(command, "Windows code signing failed")

    def verify(self, artifact_path: Path, *, require_timestamp: bool) -> bool:
        command = [str(self.signtool_path), "verify", "/pa", "/all"]
        if require_timestamp:
            command.append("/tw")
        command.append(str(artifact_path))
        result = subprocess.run(command, capture_output=True, check=False, shell=False)
        return result.returncode == 0


@dataclass(frozen=True, slots=True)
class Ed25519PemManifestSigner:
    """Detached signer that loads private material only from an external file."""

    private_key_path: Path
    password: bytes | None = field(default=None, repr=False)

    def _private_key(self) -> Ed25519PrivateKey:
        key = load_pem_private_key(self.private_key_path.read_bytes(), password=self.password)
        if not isinstance(key, Ed25519PrivateKey):
            raise TypeError("release manifest private key must be Ed25519")
        return key

    @property
    def public_key_pem(self) -> bytes:
        return (
            self._private_key()
            .public_key()
            .public_bytes(
                encoding=Encoding.PEM,
                format=PublicFormat.SubjectPublicKeyInfo,
            )
        )

    def sign(self, content: bytes) -> bytes:
        return self._private_key().sign(content)


def sign_release_artifacts(
    *,
    code_artifacts: tuple[Path, ...],
    distribution_kind: DistributionKind,
    code_signer: CodeSigningBackend | None,
    timestamp_url: str | None,
    bundle_root: Path | None = None,
    manifest_parameters: ReleaseManifestParameters | None = None,
    manifest_signer: DetachedManifestSigner | None = None,
    embedded_release_public_key_pem: bytes | None = None,
) -> SigningEvidence:
    """Sign exact code artifacts, then generate and authenticate the post-sign manifest."""

    if distribution_kind not in {"DEVELOPMENT", "STAGING", "PRODUCTION"}:
        raise ValueError("unsupported distribution kind")
    requires_authenticode = distribution_kind in {"STAGING", "PRODUCTION"}
    if requires_authenticode and (code_signer is None or not timestamp_url):
        raise ValueError("distributed artifacts require code signing and timestamping")
    normalized_artifacts = tuple(sorted((path.resolve() for path in code_artifacts), key=str))
    if len(normalized_artifacts) != len(set(normalized_artifacts)):
        raise ValueError("code artifacts must be unique")
    if bundle_root is not None:
        _require_complete_bundle_executable_set(bundle_root.resolve(), normalized_artifacts)
        if manifest_parameters is None or manifest_signer is None:
            raise ValueError("bundle signing requires manifest parameters and a detached signer")
        if requires_authenticode and embedded_release_public_key_pem is None:
            raise ValueError("distributed bundle requires the Launcher embedded release public key")
        if (
            embedded_release_public_key_pem is not None
            and manifest_signer.public_key_pem != embedded_release_public_key_pem
        ):
            raise ValueError(
                "manifest signer does not match the Launcher embedded release public key"
            )
    elif (
        manifest_parameters is not None
        or manifest_signer is not None
        or embedded_release_public_key_pem is not None
    ):
        raise ValueError("manifest inputs require bundle_root")

    signed: list[Path] = []
    for artifact in normalized_artifacts:
        if not artifact.is_file():
            raise FileNotFoundError(f"code artifact missing: {artifact}")
        if code_signer is None:
            continue
        code_signer.sign(artifact, timestamp_url=timestamp_url or "")
        if not code_signer.verify(artifact, require_timestamp=requires_authenticode):
            raise RuntimeError(f"code signature verification failed: {artifact.name}")
        signed.append(artifact)

    manifest_path: Path | None = None
    signature_path: Path | None = None
    public_key_hash: str | None = None
    if bundle_root is not None and manifest_parameters is not None and manifest_signer is not None:
        root = bundle_root.resolve()
        generate_release_manifest(bundle_root=root, parameters=manifest_parameters)
        manifest_path = root / "release-manifest.json"
        manifest_bytes = manifest_path.read_bytes()
        signature = manifest_signer.sign(manifest_bytes)
        if len(signature) != 64:
            raise ValueError("release manifest signer returned an invalid Ed25519 signature")
        public_key = _load_public_key(manifest_signer.public_key_pem)
        try:
            public_key.verify(signature, manifest_bytes)
        except InvalidSignature as error:
            raise RuntimeError("release manifest signature self-verification failed") from error
        signature_path = root / "release-manifest.sig"
        signature_path.write_text(
            base64.b64encode(signature).decode("ascii") + "\n",
            encoding="ascii",
        )
        public_key_hash = hashlib.sha256(manifest_signer.public_key_pem).hexdigest()

    return SigningEvidence(
        signed_code_artifacts=tuple(signed),
        manifest_path=manifest_path,
        manifest_signature_path=signature_path,
        release_public_key_sha256=public_key_hash,
        timestamp_url=timestamp_url,
    )


def _require_complete_bundle_executable_set(
    bundle_root: Path,
    code_artifacts: tuple[Path, ...],
) -> None:
    if not bundle_root.is_dir():
        raise ValueError("bundle_root must be an existing directory")
    expected = {
        path.resolve()
        for path in bundle_root.rglob("*")
        if path.is_file() and path.suffix.lower() in {".exe", ".dll", ".pyd"}
    }
    actual = set(code_artifacts)
    if expected != actual:
        missing = sorted(path.name for path in expected - actual)
        extra = sorted(path.name for path in actual - expected)
        raise ValueError(f"code signing artifact set mismatch: missing={missing}, extra={extra}")


def _load_public_key(content: bytes) -> Ed25519PublicKey:
    from cryptography.hazmat.primitives.serialization import load_pem_public_key

    key = load_pem_public_key(content)
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("release manifest public key must be Ed25519")
    return key


def _run_sign_tool(command: tuple[str, ...], error_message: str) -> None:
    result = subprocess.run(command, capture_output=True, check=False, shell=False)
    if result.returncode != 0:
        raise RuntimeError(error_message)


__all__ = [
    "CodeSigningBackend",
    "DetachedManifestSigner",
    "Ed25519PemManifestSigner",
    "SigningEvidence",
    "WindowsSignToolBackend",
    "sign_release_artifacts",
]
