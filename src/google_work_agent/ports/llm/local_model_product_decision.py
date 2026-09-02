"""Signed release-selection decision for one LOCAL_CAPABLE model."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal

from google_work_agent.ports.llm.approved_model_manifest import validate_concrete_sha256


@dataclass(frozen=True, slots=True)
class LocalModelProductDecisionV1:
    schema_version: Literal[1]
    decision_status: Literal["APPROVED_FOR_LOCAL_PROFILE"]
    release_version: str
    deployment_profile: Literal["LOCAL_CAPABLE"]
    selected_model_id: str
    model_manifest_hash: str
    candidate_config_hash: str
    minimum_cpu_logical_cores: int
    minimum_ram_bytes: int
    minimum_vram_bytes: int
    supported_os: Literal["WINDOWS"]
    supported_architecture: Literal["AMD64"]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported LocalModelProductDecisionV1 schema_version")
        if self.decision_status != "APPROVED_FOR_LOCAL_PROFILE":
            raise ValueError("local model decision is not approved")
        if self.deployment_profile != "LOCAL_CAPABLE":
            raise ValueError("local model decision profile mismatch")
        if not self.release_version.strip() or not self.selected_model_id.strip():
            raise ValueError("local model decision identity is required")
        validate_concrete_sha256(self.model_manifest_hash, field_name="model_manifest_hash")
        validate_concrete_sha256(self.candidate_config_hash, field_name="candidate_config_hash")
        if (
            self.minimum_cpu_logical_cores < 1
            or self.minimum_ram_bytes < 1
            or self.minimum_vram_bytes < 1
        ):
            raise ValueError("local hardware requirements must be positive")
        if self.supported_os != "WINDOWS" or self.supported_architecture != "AMD64":
            raise ValueError("unsupported local runtime platform decision")

    def to_canonical_bytes(self) -> bytes:
        return json.dumps(
            asdict(self), sort_keys=True, separators=(",", ":"), ensure_ascii=True
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, content: bytes) -> LocalModelProductDecisionV1:
        decoded = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        expected_fields = {
            "schema_version",
            "decision_status",
            "release_version",
            "deployment_profile",
            "selected_model_id",
            "model_manifest_hash",
            "candidate_config_hash",
            "minimum_cpu_logical_cores",
            "minimum_ram_bytes",
            "minimum_vram_bytes",
            "supported_os",
            "supported_architecture",
        }
        if not isinstance(decoded, dict) or set(decoded) != expected_fields:
            raise ValueError("LocalModelProductDecisionV1 fields mismatch")
        string_fields = expected_fields - {
            "schema_version",
            "minimum_cpu_logical_cores",
            "minimum_ram_bytes",
            "minimum_vram_bytes",
        }
        if decoded["schema_version"] != 1 or any(
            not isinstance(decoded[field], str) for field in string_fields
        ):
            raise ValueError("LocalModelProductDecisionV1 field type mismatch")
        for field in (
            "minimum_cpu_logical_cores",
            "minimum_ram_bytes",
            "minimum_vram_bytes",
        ):
            if not isinstance(decoded[field], int) or isinstance(decoded[field], bool):
                raise ValueError("LocalModelProductDecisionV1 field type mismatch")
        return cls(**decoded)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = ["LocalModelProductDecisionV1"]
