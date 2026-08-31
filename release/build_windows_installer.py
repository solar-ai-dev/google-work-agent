"""Build the canonical Windows installer from a signed verified bundle."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, cast

from installer.windows.installer_definition import WindowsInstallerDefinition
from launcher.verify_installation import verify_installation

from release.sign_release_artifacts import CodeSigningBackend


class WindowsInstallerBackend(Protocol):
    def build(self, *, definition_path: Path, output_dir: Path) -> Path: ...


@dataclass(frozen=True, slots=True)
class InnoSetupBackend:
    compiler_path: Path

    def build(self, *, definition_path: Path, output_dir: Path) -> Path:
        if not self.compiler_path.is_file():
            raise FileNotFoundError("Inno Setup compiler is unavailable")
        result = subprocess.run(
            (str(self.compiler_path), "/Qp", str(definition_path)),
            cwd=definition_path.parent,
            capture_output=True,
            check=False,
            shell=False,
        )
        if result.returncode != 0:
            raise RuntimeError("Windows installer backend failed")
        installers = tuple(output_dir.glob("GoogleWorkAgent-*-Setup.exe"))
        if len(installers) != 1:
            raise RuntimeError("Windows installer backend produced an unexpected artifact set")
        return installers[0]


def build_windows_installer(
    *,
    bundle_root: Path,
    output_dir: Path,
    trusted_release_public_key_pem: bytes,
    backend: WindowsInstallerBackend,
    code_signature_verifier: CodeSigningBackend | None,
    installer_definition: WindowsInstallerDefinition | None = None,
) -> Path:
    """Verify the signed bundle and invoke exactly one Windows installer backend."""

    installation = verify_installation(
        bundle_root.resolve(),
        trusted_public_key_pem=trusted_release_public_key_pem,
    )
    manifest = installation.manifest
    _require_manifest_covers_current_bundle(installation.install_root, manifest["files"])
    build_channel = str(manifest["build_channel"]).upper()
    requires_code_signatures = build_channel != "DEVELOPMENT"
    executable_paths = tuple(
        sorted(
            path
            for path in installation.verified_files
            if path.suffix.lower() in {".exe", ".dll", ".pyd"}
        )
    )
    if requires_code_signatures and code_signature_verifier is None:
        raise ValueError("distributed bundle requires Authenticode verification")
    if code_signature_verifier is not None:
        for executable in executable_paths:
            if not code_signature_verifier.verify(
                executable,
                require_timestamp=requires_code_signatures,
            ):
                raise RuntimeError(f"bundle code signature verification failed: {executable.name}")

    destination = output_dir.resolve()
    destination.mkdir(parents=True, exist_ok=True)
    definition = installer_definition or WindowsInstallerDefinition()
    with tempfile.TemporaryDirectory(prefix="gwa-installer-") as temporary:
        definition_path = Path(temporary) / "GoogleWorkAgent.iss"
        definition_path.write_text(
            definition.render_inno_setup_script(
                bundle_root=installation.install_root,
                output_dir=destination,
                app_version=str(manifest["app_version"]),
                deployment_profile=str(manifest["deployment_profile"]),
            ),
            encoding="utf-8",
        )
        artifact = backend.build(definition_path=definition_path, output_dir=destination)
    resolved_artifact = artifact.resolve()
    try:
        resolved_artifact.relative_to(destination)
    except ValueError as error:
        raise RuntimeError("installer backend artifact escaped output directory") from error
    if not resolved_artifact.is_file() or resolved_artifact.suffix.lower() != ".exe":
        raise RuntimeError("installer backend did not produce a Windows executable")
    return resolved_artifact


def discover_inno_setup_backend() -> InnoSetupBackend:
    """Resolve an installed compiler without downloading or mutating the build host."""

    command = shutil.which("ISCC.exe") or shutil.which("iscc")
    if command is None:
        candidates = (
            Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
            Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
        )
        command = next((str(path) for path in candidates if path.is_file()), None)
    if command is None:
        raise FileNotFoundError("Inno Setup 6 compiler is unavailable")
    return InnoSetupBackend(Path(command).resolve())


def _require_manifest_covers_current_bundle(bundle_root: Path, raw_files: object) -> None:
    if not isinstance(raw_files, list):
        raise RuntimeError("verified ReleaseManifest files payload is invalid")
    expected = {
        str(cast(dict[str, object], entry)["file_path"])
        for entry in raw_files
        if isinstance(entry, dict)
    }
    actual = {
        path.relative_to(bundle_root).as_posix()
        for path in bundle_root.rglob("*")
        if path.is_file()
        and path.relative_to(bundle_root).as_posix()
        not in {"release-manifest.json", "release-manifest.sig"}
    }
    if expected != actual:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise RuntimeError(f"signed bundle artifact set mismatch: missing={missing}, extra={extra}")


__all__ = ["build_windows_installer"]
