"""Generate the unique canonical ReleaseManifestV1 authority."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from google_work_agent.adapters.connectors.runtime.load_installed_connector_manifest import (
    load_installed_connector_manifest,
)
from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    PROTOCOL_VERSION,
    MCPServerManifest,
)
from google_work_agent.application.prompt_runtime.prompt_registry import (
    SIGNED_PROMPT_INPUT_CONTRACT_RELATIVE_PATH,
    SIGNED_PROMPT_MANIFEST_RELATIVE_PATH,
    PromptRegistry,
)
from release.profiles import DeploymentProfile
from release.profiles.api_only import build_api_only_profile
from release.profiles.local_capable import build_local_capable_profile

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EXCLUDED_SELF_AUTHENTICATING_FILES = {"release-manifest.json", "release-manifest.sig"}


@dataclass(frozen=True, slots=True)
class ReleaseManifestFileV1:
    file_path: str
    file_size: int
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.file_path)
        if (
            not self.file_path
            or path.is_absolute()
            or path.as_posix() != self.file_path
            or ".." in path.parts
        ):
            raise ValueError("release manifest file_path must be safe and relative")
        if self.file_size < 0:
            raise ValueError("release manifest file_size must be nonnegative")
        if _SHA256_PATTERN.fullmatch(self.sha256) is None:
            raise ValueError("release manifest sha256 must be lowercase SHA-256")


@dataclass(frozen=True, slots=True)
class ReleaseManifestV1:
    schema_version: Literal[1]
    app_version: str
    build_channel: str
    deployment_profile: Literal["API_ONLY", "LOCAL_CAPABLE"]
    oauth_env: Literal["DEVELOPMENT", "STAGING", "PRODUCTION"]
    oauth_client_id: str
    api_contract_version: str
    mcp_schema_version: str
    policy_version: str
    database_migration_version: str
    files: tuple[ReleaseManifestFileV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported ReleaseManifestV1 schema_version")
        if self.deployment_profile not in {"API_ONLY", "LOCAL_CAPABLE"}:
            raise ValueError("unsupported deployment_profile")
        if self.oauth_env not in {"DEVELOPMENT", "STAGING", "PRODUCTION"}:
            raise ValueError("unsupported oauth_env")
        for field_name in (
            "app_version",
            "build_channel",
            "oauth_client_id",
            "api_contract_version",
            "mcp_schema_version",
            "policy_version",
            "database_migration_version",
        ):
            if not str(getattr(self, field_name)).strip():
                raise ValueError(f"{field_name} is required")
        file_paths = [entry.file_path for entry in self.files]
        if not file_paths or file_paths != sorted(file_paths):
            raise ValueError("release manifest files must be nonempty and sorted")
        if len(file_paths) != len(set(file_paths)):
            raise ValueError("release manifest file_path values must be unique")

    def to_payload(self) -> dict[str, object]:
        payload = asdict(self)
        payload["files"] = [asdict(entry) for entry in self.files]
        return payload

    def to_canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_payload(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")


@dataclass(frozen=True, slots=True)
class ReleaseManifestParameters:
    app_version: str
    build_channel: str
    deployment_profile: DeploymentProfile
    oauth_env: Literal["DEVELOPMENT", "STAGING", "PRODUCTION"]
    oauth_client_id: str
    api_contract_version: str
    mcp_schema_version: str
    policy_version: str
    database_migration_version: str


def generate_release_manifest(
    *,
    bundle_root: Path,
    parameters: ReleaseManifestParameters,
    output_path: Path | None = None,
) -> ReleaseManifestV1:
    """Hash the exact profile bundle and write its deterministic closed manifest."""

    root = bundle_root.resolve()
    if not root.is_dir():
        raise ValueError("bundle_root must be an existing directory")
    _validate_prompt_bundle(root)
    files = tuple(_manifest_entry(root, path) for path in _iter_release_files(root))
    relative_paths = tuple(entry.file_path for entry in files)
    profile = (
        build_api_only_profile()
        if parameters.deployment_profile is DeploymentProfile.API_ONLY
        else build_local_capable_profile()
    )
    profile.validate(relative_paths)
    _validate_connector_contract(root, parameters.mcp_schema_version)
    manifest = ReleaseManifestV1(
        schema_version=1,
        app_version=parameters.app_version,
        build_channel=parameters.build_channel,
        deployment_profile=parameters.deployment_profile.value,
        oauth_env=parameters.oauth_env,
        oauth_client_id=parameters.oauth_client_id,
        api_contract_version=parameters.api_contract_version,
        mcp_schema_version=parameters.mcp_schema_version,
        policy_version=parameters.policy_version,
        database_migration_version=parameters.database_migration_version,
        files=files,
    )
    destination = output_path or root / "release-manifest.json"
    if destination.resolve().parent != root:
        raise ValueError("release manifest must be written at the bundle root")
    destination.write_bytes(manifest.to_canonical_bytes() + b"\n")
    return manifest


def _validate_connector_contract(root: Path, mcp_schema_version: str) -> None:
    installed = load_installed_connector_manifest(
        root / "manifests" / "installed-connectors-v1.json"
    )
    for connector in installed.connectors:
        if connector.mcp_schema_version != mcp_schema_version:
            raise ValueError("release and installed connector MCP schema versions differ")
        projection = MCPServerManifest.load(
            root / Path(*PurePosixPath(connector.tool_projection_path).parts)
        )
        if (
            projection.connector_id != connector.connector_id
            or projection.manifest_version != mcp_schema_version
            or projection.protocol_version != PROTOCOL_VERSION
        ):
            raise ValueError("installed connector MCP projection contract mismatch")


def _validate_prompt_bundle(root: Path) -> None:
    manifest = root / Path(*PurePosixPath(SIGNED_PROMPT_MANIFEST_RELATIVE_PATH).parts)
    input_contract = root / Path(*PurePosixPath(SIGNED_PROMPT_INPUT_CONTRACT_RELATIVE_PATH).parts)
    PromptRegistry(manifest, input_contract).require_product_release_ready()


def _iter_release_files(root: Path) -> tuple[Path, ...]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError(f"release bundle must not contain symlinks: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in _EXCLUDED_SELF_AUTHENTICATING_FILES:
            continue
        files.append(path)
    return tuple(sorted(files, key=lambda item: item.relative_to(root).as_posix()))


def _manifest_entry(root: Path, path: Path) -> ReleaseManifestFileV1:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return ReleaseManifestFileV1(
        file_path=path.relative_to(root).as_posix(),
        file_size=path.stat().st_size,
        sha256=digest.hexdigest(),
    )


__all__ = [
    "ReleaseManifestFileV1",
    "ReleaseManifestParameters",
    "ReleaseManifestV1",
    "generate_release_manifest",
]
