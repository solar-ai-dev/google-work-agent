"""Gold-free, split-neutral Node Evaluation item contract."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


class NodeEvaluationItemV1(EvaluationContract):
    schema_version: Literal[1]
    runtime_item_id: str
    target_id: str
    fixture_snapshot_id: str
    product_input: dict[str, JsonValue]

    @field_validator("runtime_item_id", "target_id", "fixture_snapshot_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Node Evaluation identities must be non-empty")
        return value


__all__ = ["NodeEvaluationItemV1"]
