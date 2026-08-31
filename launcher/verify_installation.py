"""Verify the installed Release Manifest signature and referenced file hashes."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_MANIFEST_FIELDS = {
    "schema_version",
    "app_version",
    "build_channel",
    "deployment_profile",
    "oauth_env",
    "oauth_client_id",
    "api_contract_version",
    "mcp_schema_version",
    "policy_version",
    "database_migration_version",
    "files",
}
_FILE_FIELDS = {"file_path", "file_size", "sha256"}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")

# #168 owns release key materialization. Until that build step injects the public
# key, installed startup fails closed; tests use a deterministic signed fixture.
EMBEDDED_RELEASE_PUBLIC_KEY_PEM: bytes | None = None


class InstallationVerificationError(RuntimeError):
    """Fail-closed installation trust error with a safe diagnostic code."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class VerifiedInstallation:
    """Opaque proof that the exact manifest bytes and all referenced files passed."""

    install_root: Path
    manifest_path: Path
    signature_path: Path
    manifest: Mapping[str, object]
    verified_files: tuple[Path, ...]


def verify_installation(
    install_root: Path,
    *,
    trusted_public_key_pem: bytes | None = EMBEDDED_RELEASE_PUBLIC_KEY_PEM,
) -> VerifiedInstallation:
    """Verify signature first, then the closed manifest schema and every file hash."""

    if not install_root.is_absolute():
        raise InstallationVerificationError("INSTALLATION_ROOT_INVALID")
    root = install_root.resolve()
    if not root.is_dir():
        raise InstallationVerificationError("INSTALLATION_ROOT_INVALID")
    manifest_path = root / "release-manifest.json"
    signature_path = root / "release-manifest.sig"
    if not manifest_path.is_file() or not signature_path.is_file():
        raise InstallationVerificationError("MANIFEST_MISSING")
    if trusted_public_key_pem is None:
        raise InstallationVerificationError("RELEASE_PUBLIC_KEY_UNAVAILABLE")

    try:
        if manifest_path.stat().st_size > 4 * 1024 * 1024:
            raise InstallationVerificationError("MANIFEST_INVALID")
        manifest_bytes = manifest_path.read_bytes()
    except OSError as error:
        raise InstallationVerificationError("MANIFEST_INVALID") from error
    signature = _load_signature(signature_path)
    _verify_signature(trusted_public_key_pem, manifest_bytes, signature)
    payload = _load_closed_manifest(manifest_bytes)
    verified_files = _verify_files(root, payload["files"])
    return VerifiedInstallation(
        install_root=root,
        manifest_path=manifest_path,
        signature_path=signature_path,
        manifest=MappingProxyType(payload),
        verified_files=verified_files,
    )


def _load_signature(path: Path) -> bytes:
    try:
        if path.stat().st_size > 1_024:
            raise ValueError("signature is too large")
        encoded = path.read_text(encoding="ascii").strip()
        signature = base64.b64decode(encoded, validate=True)
    except (OSError, UnicodeError, ValueError) as error:
        raise InstallationVerificationError("SIGNATURE_INVALID") from error
    if len(signature) != 64:
        raise InstallationVerificationError("SIGNATURE_INVALID")
    return signature


def _verify_signature(public_key_pem: bytes, content: bytes, signature: bytes) -> None:
    try:
        public_key = load_pem_public_key(public_key_pem)
        if not isinstance(public_key, Ed25519PublicKey):
            raise TypeError("release key must be Ed25519")
        public_key.verify(signature, content)
    except (InvalidSignature, TypeError, ValueError) as error:
        raise InstallationVerificationError("SIGNATURE_INVALID") from error


def _load_closed_manifest(content: bytes) -> dict[str, object]:
    try:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
    except (UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise InstallationVerificationError("MANIFEST_INVALID") from error
    if not isinstance(payload, dict) or set(payload) != _MANIFEST_FIELDS:
        raise InstallationVerificationError("MANIFEST_INVALID")
    if payload["schema_version"] != 1:
        raise InstallationVerificationError("MANIFEST_INVALID")
    if payload["deployment_profile"] not in {"API_ONLY", "LOCAL_CAPABLE"}:
        raise InstallationVerificationError("MANIFEST_INVALID")
    if payload["oauth_env"] not in {"DEVELOPMENT", "STAGING", "PRODUCTION"}:
        raise InstallationVerificationError("MANIFEST_INVALID")
    for field in _MANIFEST_FIELDS - {"schema_version", "deployment_profile", "oauth_env", "files"}:
        if (
            not isinstance(payload[field], str)
            or not str(payload[field]).strip()
            or len(str(payload[field])) > 512
        ):
            raise InstallationVerificationError("MANIFEST_INVALID")
    files = payload["files"]
    if not isinstance(files, list) or not files or len(files) > 10_000:
        raise InstallationVerificationError("MANIFEST_INVALID")
    return payload


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _verify_files(root: Path, raw_files: object) -> tuple[Path, ...]:
    if not isinstance(raw_files, list):
        raise InstallationVerificationError("MANIFEST_INVALID")
    seen: set[str] = set()
    verified: list[Path] = []
    for raw_entry in raw_files:
        if not isinstance(raw_entry, dict) or set(raw_entry) != _FILE_FIELDS:
            raise InstallationVerificationError("MANIFEST_INVALID")
        relative = raw_entry["file_path"]
        size = raw_entry["file_size"]
        expected_hash = raw_entry["sha256"]
        if (
            not isinstance(relative, str)
            or len(relative) > 512
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(expected_hash, str)
            or _SHA256_PATTERN.fullmatch(expected_hash) is None
        ):
            raise InstallationVerificationError("MANIFEST_INVALID")
        candidate = _resolve_manifest_child(root, relative)
        if relative in seen:
            raise InstallationVerificationError("MANIFEST_INVALID")
        seen.add(relative)
        if not candidate.is_file():
            raise InstallationVerificationError("INSTALLATION_FILE_MISSING")
        if candidate.stat().st_size != size or _hash_file(candidate) != expected_hash:
            raise InstallationVerificationError("INSTALLATION_FILE_TAMPERED")
        verified.append(candidate)
    return tuple(verified)


def _resolve_manifest_child(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if (
        not relative
        or "\\" in relative
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or path.as_posix() != relative
    ):
        raise InstallationVerificationError("MANIFEST_INVALID")
    candidate = (root / Path(*path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise InstallationVerificationError("MANIFEST_INVALID") from error
    return candidate


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
