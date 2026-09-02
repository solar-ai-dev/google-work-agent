"""Shared closed contract for release artifact profiles."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import PurePosixPath


class DeploymentProfile(StrEnum):
    API_ONLY = "API_ONLY"
    LOCAL_CAPABLE = "LOCAL_CAPABLE"


@dataclass(frozen=True, slots=True)
class ReleaseArtifactProfile:
    deployment_profile: DeploymentProfile
    runtime_modes: tuple[str, ...]
    requires_model_manifest: bool
    requires_local_model_product_decision: bool
    required_files: tuple[str, ...]
    required_nonempty_directories: tuple[str, ...]

    def validate(self, relative_paths: tuple[str, ...]) -> None:
        paths = set(relative_paths)
        if len(paths) != len(relative_paths):
            raise ValueError("release artifact paths must be unique")
        for value in paths:
            path = PurePosixPath(value)
            if path.is_absolute() or path.as_posix() != value or ".." in path.parts:
                raise ValueError(f"unsafe release artifact path: {value}")
            _reject_forbidden_path(path)
        missing = set(self.required_files) - paths
        if missing:
            raise ValueError(f"required release artifacts missing: {sorted(missing)}")
        for directory in self.required_nonempty_directories:
            prefix = f"{directory}/"
            if not any(path.startswith(prefix) for path in paths):
                raise ValueError(f"required release directory is empty: {directory}")
        model_manifest = "manifests/model-manifest-v1.json"
        product_decision = "manifests/local-model-product-decision-v1.json"
        if self.requires_model_manifest and model_manifest not in paths:
            raise ValueError("LOCAL_CAPABLE requires model-manifest-v1.json")
        if not self.requires_model_manifest and model_manifest in paths:
            raise ValueError("API_ONLY must omit model-manifest-v1.json")
        if self.requires_local_model_product_decision and product_decision not in paths:
            raise ValueError("LOCAL_CAPABLE requires local-model-product-decision-v1.json")
        if not self.requires_local_model_product_decision and product_decision in paths:
            raise ValueError("API_ONLY must omit local-model-product-decision-v1.json")


def _reject_forbidden_path(path: PurePosixPath) -> None:
    forbidden_parts = {
        "__pycache__",
        "tests",
        "evaluation",
        "evaluations",
        "experiments",
        ".git",
        "node_modules",
    }
    forbidden_names = {
        ".env",
        ".env.local",
        "app-settings.json",
        "approved-models.json",
        "build-config.json",
        "config.json",
        "node.exe",
        "npm",
        "npm.cmd",
        "profile-api_only.json",
        "profile-local_capable.json",
    }
    if any(part.lower() in forbidden_parts for part in path.parts):
        raise ValueError(f"forbidden release path: {path.as_posix()}")
    if path.name.lower() in forbidden_names or path.suffix.lower() in {".map", ".py", ".pyc"}:
        raise ValueError(f"forbidden release artifact: {path.as_posix()}")


__all__ = ["DeploymentProfile", "ReleaseArtifactProfile"]
