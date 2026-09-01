"""Assemble the single canonical one-folder application bundle."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import cast

from installer.windows.installer_definition import WindowsInstallerDefinition
from installer.windows.uninstall_definition import WindowsUninstallDefinition
from installer.windows.upgrade_policy import WindowsUpgradePolicy

from google_work_agent.adapters.connectors.runtime.load_installed_connector_manifest import (
    load_installed_connector_manifest,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    build_manifest_payload_for_descriptors,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from release.generate_model_manifest import ModelManifestV1
from release.profiles import DeploymentProfile, ReleaseArtifactProfile
from release.profiles.api_only import build_api_only_profile
from release.profiles.local_capable import build_local_capable_profile

_TEXT_SUFFIXES = {".cfg", ".html", ".ini", ".js", ".json", ".md", ".txt", ".xml"}
_FORBIDDEN_CONTENT = (
    b"OAUTH_CLIENT_SECRET",
    b'"client_secret"',
    b"-----BEGIN PRIVATE KEY-----",
)


@dataclass(frozen=True, slots=True)
class ApplicationBundleInputs:
    launcher_distribution: Path
    service_distribution: Path
    frontend_distribution: Path
    mcp_distribution: Path
    runtime_distribution: Path
    schemas: Path
    migrations: Path
    uninstaller_distribution: Path
    installed_connector_manifest: Path
    signed_tool_registry: Path
    model_manifest: Path | None = None


def assemble_application_bundle(
    *,
    profile: DeploymentProfile,
    inputs: ApplicationBundleInputs,
    output_root: Path,
    installer_definition: WindowsInstallerDefinition | None = None,
    uninstall_definition: WindowsUninstallDefinition | None = None,
    upgrade_policy: WindowsUpgradePolicy | None = None,
) -> tuple[str, ...]:
    """Copy verified build inputs, materialize projections, and reject unsafe payloads."""

    destination = output_root.resolve()
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("output_root must be absent or empty")
    destination.mkdir(parents=True, exist_ok=True)
    for source, relative in (
        (inputs.launcher_distribution, "launcher"),
        (inputs.service_distribution, "service"),
        (inputs.frontend_distribution, "frontend"),
        (inputs.mcp_distribution, "mcp"),
        (inputs.runtime_distribution, "runtime"),
        (inputs.schemas, "schemas"),
        (inputs.migrations, "migrations"),
        (inputs.uninstaller_distribution, "uninstaller"),
    ):
        _copy_distribution(source, destination / relative)

    manifests_dir = destination / "manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    _materialize_connector_artifacts(
        destination=destination,
        installed_connector_manifest=inputs.installed_connector_manifest,
        signed_tool_registry=inputs.signed_tool_registry,
    )
    if profile is DeploymentProfile.LOCAL_CAPABLE:
        if inputs.model_manifest is None or not inputs.model_manifest.is_file():
            raise ValueError("LOCAL_CAPABLE requires an explicit generated model manifest")
        model_manifest = ModelManifestV1.from_bytes(inputs.model_manifest.read_bytes())
        (manifests_dir / "model-manifest-v1.json").write_bytes(
            model_manifest.to_canonical_bytes() + b"\n"
        )
    elif inputs.model_manifest is not None:
        raise ValueError("API_ONLY must not receive a model manifest")

    definitions = (
        (
            "installer-definition-v1.json",
            (installer_definition or WindowsInstallerDefinition()).to_canonical_json(),
        ),
        (
            "uninstall-policy-v1.json",
            (uninstall_definition or WindowsUninstallDefinition()).to_canonical_json(),
        ),
        (
            "upgrade-policy-v1.json",
            (upgrade_policy or WindowsUpgradePolicy()).to_canonical_json(),
        ),
    )
    for filename, content in definitions:
        (destination / "uninstaller" / filename).write_text(content + "\n", encoding="utf-8")

    relative_paths = _relative_files(destination)
    _profile(profile).validate(relative_paths)
    _validate_bundle_content(destination, relative_paths)
    return relative_paths


def _materialize_connector_artifacts(
    *,
    destination: Path,
    installed_connector_manifest: Path,
    signed_tool_registry: Path,
) -> None:
    installed = load_installed_connector_manifest(installed_connector_manifest)
    registry = load_signed_tool_registry(signed_tool_registry)
    installed_payload = _read_object(installed_connector_manifest)
    registry_payload = _read_object(signed_tool_registry)
    manifests_dir = destination / "manifests"
    _write_canonical_json(manifests_dir / "installed-connectors-v1.json", installed_payload)
    _write_canonical_json(manifests_dir / "signed-tool-registry-v1.json", registry_payload)
    for connector in installed.connectors:
        executable = _safe_child(destination, connector.executable_path)
        if not executable.is_file():
            raise ValueError(f"installed connector executable missing: {connector.executable_path}")
        descriptors = registry.descriptor_expectations(connector.connector_id)
        if not descriptors:
            raise ValueError(f"installed connector has no signed tools: {connector.connector_id}")
        projection = build_manifest_payload_for_descriptors(
            connector_id=connector.connector_id,
            registry_manifest_hash=registry.entries_hash,
            descriptors=tuple(descriptors),
        )
        if projection["manifest_version"] != connector.mcp_schema_version:
            raise ValueError("installed connector MCP schema version mismatch")
        projection_path = _safe_child(destination, connector.tool_projection_path)
        _write_canonical_json(projection_path, projection)


def _copy_distribution(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"release input directory missing: {source}")
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_symlink():
            raise ValueError(f"release input must not contain symlinks: {path}")
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def _read_object(path: Path) -> dict[str, object]:
    decoded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError(f"manifest must be an object: {path}")
    return cast(dict[str, object], decoded)


def _write_canonical_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def _safe_child(root: Path, relative: str) -> Path:
    path = PurePosixPath(relative)
    if path.is_absolute() or path.as_posix() != relative or ".." in path.parts:
        raise ValueError(f"unsafe installed artifact path: {relative}")
    candidate = (root / Path(*path.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError(f"installed artifact escapes bundle: {relative}") from error
    return candidate


def _relative_files(root: Path) -> tuple[str, ...]:
    return tuple(
        sorted(path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file())
    )


def _profile(profile: DeploymentProfile) -> ReleaseArtifactProfile:
    return (
        build_api_only_profile()
        if profile is DeploymentProfile.API_ONLY
        else build_local_capable_profile()
    )


def _validate_bundle_content(root: Path, relative_paths: tuple[str, ...]) -> None:
    for relative in relative_paths:
        path = root / Path(*PurePosixPath(relative).parts)
        lowered_name = path.name.lower()
        if lowered_name.startswith(".env") or "client_secret" in lowered_name:
            raise ValueError(f"sensitive release artifact name rejected: {relative}")
        if path.suffix.lower() not in _TEXT_SUFFIXES or path.stat().st_size > 8 * 1024 * 1024:
            continue
        content = path.read_bytes()
        if any(marker in content for marker in _FORBIDDEN_CONTENT):
            raise ValueError(f"sensitive release artifact content rejected: {relative}")


__all__ = ["ApplicationBundleInputs", "assemble_application_bundle"]
