"""Verify the installed Release Manifest signature and referenced file hashes."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
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
_INSTALLER_GENERATED_FILES = {"unins000.dat", "unins000.exe"}

# Canonical production trust root. The matching private key is release-operator
# owned and must never be stored in the repository or distributed application.
EMBEDDED_RELEASE_PUBLIC_KEY_PEM = b"""-----BEGIN PUBLIC KEY-----
MCowBQYDK2VwAyEACI9ODzz4QkGyhUSdKFFeVRWvlq9tT5h6segP6i07dog=
-----END PUBLIC KEY-----
"""
EMBEDDED_RELEASE_PUBLIC_KEY_SHA256 = (
    "a38089529f535f281192edaad5d528fa87f031c6ab2756dadac9bf7ba0a0b300"
)


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
    code_signature_verified_files: tuple[Path, ...] = ()


def verify_installation(
    install_root: Path,
    *,
    trusted_public_key_pem: bytes | None = EMBEDDED_RELEASE_PUBLIC_KEY_PEM,
    code_signature_verifier: Callable[[Path], bool] | None = None,
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
    installer_generated_files = _reject_unlisted_installed_files(root, payload["files"])
    code_signature_verified_files = _verify_code_signatures(
        verified_files
        + tuple(path for path in installer_generated_files if path.suffix.lower() == ".exe"),
        build_channel=str(payload["build_channel"]),
        verifier=code_signature_verifier,
    )
    return VerifiedInstallation(
        install_root=root,
        manifest_path=manifest_path,
        signature_path=signature_path,
        manifest=MappingProxyType(payload),
        verified_files=verified_files,
        code_signature_verified_files=code_signature_verified_files,
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
    ordered_paths: list[str] = []
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
        ordered_paths.append(relative)
        try:
            if not candidate.is_file():
                raise InstallationVerificationError("INSTALLATION_FILE_MISSING")
            if candidate.stat().st_size != size or _hash_file(candidate) != expected_hash:
                raise InstallationVerificationError("INSTALLATION_FILE_TAMPERED")
        except OSError as error:
            raise InstallationVerificationError("INSTALLATION_FILE_MISSING") from error
        verified.append(candidate)
    if ordered_paths != sorted(ordered_paths):
        raise InstallationVerificationError("MANIFEST_INVALID")
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
    lexical_candidate = root / Path(*path.parts)
    current = lexical_candidate
    while current != root:
        if current.is_symlink():
            raise InstallationVerificationError("INSTALLATION_FILE_TAMPERED")
        current = current.parent
    candidate = lexical_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise InstallationVerificationError("MANIFEST_INVALID") from error
    return candidate


def _reject_unlisted_installed_files(root: Path, raw_files: object) -> tuple[Path, ...]:
    if not isinstance(raw_files, list):
        raise InstallationVerificationError("MANIFEST_INVALID")
    expected = {
        str(entry["file_path"])
        for entry in raw_files
        if isinstance(entry, dict) and isinstance(entry.get("file_path"), str)
    }
    actual: set[str] = set()
    installer_generated: set[str] = set()
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {"release-manifest.json", "release-manifest.sig"}:
            continue
        if relative.lower() in _INSTALLER_GENERATED_FILES:
            installer_generated.add(relative)
            continue
        actual.add(relative)
    if expected != actual:
        raise InstallationVerificationError("INSTALLATION_ARTIFACT_SET_MISMATCH")
    if installer_generated and {path.lower() for path in installer_generated} != (
        _INSTALLER_GENERATED_FILES
    ):
        raise InstallationVerificationError("INSTALLATION_ARTIFACT_SET_MISMATCH")
    return tuple(root / path for path in sorted(installer_generated))


def _verify_code_signatures(
    verified_files: tuple[Path, ...],
    *,
    build_channel: str,
    verifier: Callable[[Path], bool] | None,
) -> tuple[Path, ...]:
    if build_channel.upper() == "DEVELOPMENT":
        return ()
    executable_files = tuple(
        path for path in verified_files if path.suffix.lower() in {".dll", ".exe", ".pyd"}
    )
    active_verifier = verifier or _verify_windows_authenticode
    if not executable_files or any(not active_verifier(path) for path in executable_files):
        raise InstallationVerificationError("INSTALLATION_CODE_SIGNATURE_INVALID")
    return executable_files


def _verify_windows_authenticode(path: Path) -> bool:
    if sys.platform != "win32":
        return False
    powershell = (
        Path(os.environ.get("SYSTEMROOT", r"C:\Windows"))
        / "System32"
        / "WindowsPowerShell"
        / "v1.0"
        / "powershell.exe"
    )
    if not powershell.is_file():
        return False
    script = (
        "$signature = Get-AuthenticodeSignature -LiteralPath $args[0]; "
        "if ($signature.Status -eq 'Valid' -and "
        "$null -ne $signature.SignerCertificate -and "
        "$null -ne $signature.TimeStamperCertificate) { exit 0 } else { exit 1 }"
    )
    try:
        result = subprocess.run(
            (
                str(powershell),
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                script,
                str(path),
            ),
            capture_output=True,
            check=False,
            shell=False,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
