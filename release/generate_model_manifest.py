"""Materialize the canonical LOCAL_CAPABLE model allowlist manifest."""

from __future__ import annotations

from pathlib import Path

from google_work_agent.ports.llm.approved_model_manifest import (
    ApprovedModelEntryV1,
    ModelManifestV1,
)


def generate_model_manifest(
    *,
    minimum_ollama_version: str,
    approved_models: tuple[ApprovedModelEntryV1, ...],
    output_path: Path,
) -> ModelManifestV1:
    """Materialize only an explicit release/evaluation-approved model decision."""

    manifest = ModelManifestV1(
        schema_version=1,
        minimum_ollama_version=minimum_ollama_version,
        approved_models=tuple(sorted(approved_models, key=lambda entry: entry.model_id)),
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(manifest.to_canonical_bytes() + b"\n")
    return manifest


__all__ = ["ApprovedModelEntryV1", "ModelManifestV1", "generate_model_manifest"]
