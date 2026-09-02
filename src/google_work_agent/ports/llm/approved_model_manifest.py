"""Canonical schema and parser for the signed Ollama model allowlist."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_VERSION_PATTERN = re.compile(r"\d+(?:\.\d+){1,3}")
_MODEL_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")
_PLACEHOLDER_MODEL_IDS = {"approved-model", "model", "placeholder", "todo"}


def validate_concrete_sha256(value: str, *, field_name: str) -> str:
    if _SHA256_PATTERN.fullmatch(value) is None or len(set(value)) == 1:
        raise ValueError(f"{field_name} must be a concrete lowercase SHA-256")
    return value


@dataclass(frozen=True, slots=True)
class ApprovedModelEntryV1:
    model_id: str
    model_hash: str

    def __post_init__(self) -> None:
        if (
            self.model_id != self.model_id.strip()
            or _MODEL_ID_PATTERN.fullmatch(self.model_id) is None
            or self.model_id.lower() in _PLACEHOLDER_MODEL_IDS
        ):
            raise ValueError("model_id must be a concrete release-approved model identity")
        validate_concrete_sha256(self.model_hash, field_name="model_hash")


@dataclass(frozen=True, slots=True)
class ModelManifestV1:
    schema_version: Literal[1]
    minimum_ollama_version: str
    approved_models: tuple[ApprovedModelEntryV1, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported ModelManifestV1 schema_version")
        if _VERSION_PATTERN.fullmatch(self.minimum_ollama_version) is None:
            raise ValueError("minimum_ollama_version must be a concrete dotted version")
        if not self.approved_models:
            raise ValueError("LOCAL_CAPABLE requires at least one approved model")
        model_ids = [entry.model_id for entry in self.approved_models]
        if len(model_ids) != len(set(model_ids)):
            raise ValueError("approved model_id values must be unique")
        if model_ids != sorted(model_ids):
            raise ValueError("approved models must be sorted by model_id")

    def to_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "minimum_ollama_version": self.minimum_ollama_version,
            "approved_models": [asdict(entry) for entry in self.approved_models],
        }

    @classmethod
    def from_bytes(cls, content: bytes) -> ModelManifestV1:
        decoded = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        if not isinstance(decoded, dict) or set(decoded) != {
            "schema_version",
            "minimum_ollama_version",
            "approved_models",
        }:
            raise ValueError("ModelManifestV1 fields mismatch")
        if decoded["schema_version"] != 1 or not isinstance(
            decoded["minimum_ollama_version"], str
        ):
            raise ValueError("ModelManifestV1 field type mismatch")
        raw_models = decoded["approved_models"]
        if not isinstance(raw_models, list):
            raise ValueError("approved_models must be a list")
        entries: list[ApprovedModelEntryV1] = []
        for raw_entry in raw_models:
            if not isinstance(raw_entry, dict) or set(raw_entry) != {"model_id", "model_hash"}:
                raise ValueError("ApprovedModelEntryV1 fields mismatch")
            model_id = raw_entry["model_id"]
            model_hash = raw_entry["model_hash"]
            if not isinstance(model_id, str) or not isinstance(model_hash, str):
                raise ValueError("ApprovedModelEntryV1 field type mismatch")
            entries.append(ApprovedModelEntryV1(model_id=model_id, model_hash=model_hash))
        return cls(
            schema_version=1,
            minimum_ollama_version=decoded["minimum_ollama_version"],
            approved_models=tuple(entries),
        )

    def to_canonical_bytes(self) -> bytes:
        return json.dumps(
            self.to_payload(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = [
    "ApprovedModelEntryV1",
    "ModelManifestV1",
    "validate_concrete_sha256",
]
