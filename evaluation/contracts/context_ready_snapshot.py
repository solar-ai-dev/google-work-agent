"""Gold-free controlled runtime snapshots consumed by Evaluation."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


class EvaluationPolicyProjectionV1(EvaluationContract):
    schema_version: Literal[1]
    source_case_id: str
    policy_summary: dict[str, JsonValue]


class ContextReadySnapshotV1(EvaluationContract):
    schema_version: Literal[1]
    context_snapshot_id: str
    source_case_id: str
    fixture_snapshot_id: str
    request_intent: JsonValue
    context_bundle: JsonValue
    evidence_set: list[JsonValue]
    policy_projection: EvaluationPolicyProjectionV1

    @field_validator("context_snapshot_id", "source_case_id", "fixture_snapshot_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("snapshot identity must be non-empty")
        return value
