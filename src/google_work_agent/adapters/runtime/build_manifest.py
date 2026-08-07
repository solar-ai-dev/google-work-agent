"""Signed build manifest models and deterministic verification."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

from google_work_agent.ports import ArtifactSignatureVerifier, ReadinessCheckResult, ReadinessState


class BuildProfile(StrEnum):
    API_ONLY = "API_ONLY"
    LOCAL_CAPABLE = "LOCAL_CAPABLE"


class SigningStatus(StrEnum):
    NOT_RUN = "NOT_RUN"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class BuildArtifactType(StrEnum):
    FRONTEND = "FRONTEND"
    PYTHON_MODULE = "PYTHON_MODULE"
    EXECUTABLE = "EXECUTABLE"
    DATA = "DATA"
    MANIFEST = "MANIFEST"


@dataclass(frozen=True, slots=True)
class ArtifactRecord:
    relative_install_path: str
    sha256: str
    size_bytes: int
    artifact_type: BuildArtifactType
    executable: bool
    required: bool


@dataclass(frozen=True, slots=True)
class SignedBuildManifest:
    schema_version: int
    product_name: str
    release_version: str
    build_id: str
    build_profile: BuildProfile
    api_contract_version: str
    domain_contract_version: str
    database_schema_version: str
    frontend_manifest_version: str
    frontend_asset_hashes: dict[str, str]
    service_artifact: ArtifactRecord
    mcp_artifact: ArtifactRecord
    runtime_components: tuple[ArtifactRecord, ...]
    mcp_manifest_version: str
    tool_registry_version: str
    created_at_ms: int
    signing_status: SigningStatus = SigningStatus.NOT_RUN

    def to_canonical_json(self) -> str:
        return _canonical_json(asdict(self))

    def content_sha256(self) -> str:
        return hashlib.sha256(self.to_canonical_json().encode("utf-8")).hexdigest()


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(64 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(payload: object) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


@dataclass(frozen=True, slots=True)
class FrontendSite:
    root: Path
    release_version: str
    api_contract_version: str
    manifest_version: str
    asset_hashes: dict[str, str]

    @property
    def index_path(self) -> Path:
        return self.root / "index.html"

    def readiness_check(self) -> ReadinessCheckResult:
        if not self.index_path.is_file():
            return ReadinessCheckResult(
                name="frontend_assets",
                state=ReadinessState.NOT_READY,
                detail="index.html missing",
            )
        for relative_path, expected_hash in self.asset_hashes.items():
            candidate = _safe_child(self.root, relative_path)
            if candidate is None or not candidate.is_file():
                return ReadinessCheckResult(
                    name="frontend_assets",
                    state=ReadinessState.NOT_READY,
                    detail=f"missing asset: {relative_path}",
                )
            actual_hash = hash_file(candidate)
            if actual_hash != expected_hash:
                return ReadinessCheckResult(
                    name="frontend_assets",
                    state=ReadinessState.NOT_READY,
                    detail=f"hash mismatch: {relative_path}",
                )
        if any(path.suffix == ".map" for path in self.root.rglob("*.map")):
            return ReadinessCheckResult(
                name="frontend_assets",
                state=ReadinessState.NOT_READY,
                detail="source maps are not allowed",
            )
        return ReadinessCheckResult(name="frontend_assets", state=ReadinessState.READY)

    def resolve_asset(self, relative_path: str) -> Path | None:
        if relative_path in {"", "/"}:
            return self.index_path
        normalized = relative_path.lstrip("/")
        return _safe_child(self.root, normalized)


@dataclass(frozen=True, slots=True)
class BuildManifestVerifier:
    manifest: SignedBuildManifest
    install_root: Path
    signature_verifier: ArtifactSignatureVerifier | None = None
    require_signature: bool = False

    def readiness_checks(self) -> tuple[ReadinessCheckResult, ...]:
        checks: list[ReadinessCheckResult] = [self._verify_artifacts()]
        checks.append(self._verify_signature())
        return tuple(checks)

    def _verify_artifacts(self) -> ReadinessCheckResult:
        records = (
            self.manifest.service_artifact,
            self.manifest.mcp_artifact,
            *self.manifest.runtime_components,
        )
        for record in records:
            candidate = _safe_child(self.install_root, record.relative_install_path)
            if candidate is None:
                return ReadinessCheckResult(
                    name="build_manifest",
                    state=ReadinessState.NOT_READY,
                    detail=f"path traversal blocked: {record.relative_install_path}",
                )
            if not candidate.exists():
                if record.required:
                    return ReadinessCheckResult(
                        name="build_manifest",
                        state=ReadinessState.NOT_READY,
                        detail=f"artifact missing: {record.relative_install_path}",
                    )
                continue
            if hash_file(candidate) != record.sha256:
                return ReadinessCheckResult(
                    name="build_manifest",
                    state=ReadinessState.NOT_READY,
                    detail=f"artifact hash mismatch: {record.relative_install_path}",
                )
        return ReadinessCheckResult(name="build_manifest", state=ReadinessState.READY)

    def _verify_signature(self) -> ReadinessCheckResult:
        if self.signature_verifier is None:
            if self.require_signature:
                return ReadinessCheckResult(
                    name="artifact_signature",
                    state=ReadinessState.NOT_READY,
                    detail="signature verifier missing",
                )
            return ReadinessCheckResult(
                name="artifact_signature",
                state=ReadinessState.NOT_CONFIGURED,
                detail="signing not configured",
            )
        service_path = _safe_child(
            self.install_root,
            self.manifest.service_artifact.relative_install_path,
        )
        if service_path is None:
            return ReadinessCheckResult(
                name="artifact_signature",
                state=ReadinessState.NOT_READY,
                detail="invalid service artifact path",
            )
        decision = self.signature_verifier.verify(
            executable_path=str(service_path),
            expected_binary_sha256=self.manifest.service_artifact.sha256,
        )
        if not decision.allowed:
            return ReadinessCheckResult(
                name="artifact_signature",
                state=ReadinessState.NOT_READY,
                detail=decision.detail or "signature rejected",
            )
        return ReadinessCheckResult(name="artifact_signature", state=ReadinessState.READY)


def _safe_child(root: Path, relative_path: str) -> Path | None:
    if not relative_path or Path(relative_path).is_absolute():
        return None
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate
