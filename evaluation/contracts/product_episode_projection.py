"""Product Episode evaluator-only projection contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.canonical_case import EndStateGoldV1
from evaluation.contracts.evaluation_contract import EvaluationContract


class ProductEpisodeEvaluatorInputV1(EvaluationContract):
    schema_version: Literal[1]
    decision_script: list[JsonValue]
    source_refs: list[str]


class ProductEpisodeE2EProjectionV1(EvaluationContract):
    schema_version: Literal[1]
    case_id: str
    fixture_snapshot_id: str
    product_input: JsonValue
    evaluator_input: ProductEpisodeEvaluatorInputV1
    end_state_gold: EndStateGoldV1

    @field_validator("case_id", "fixture_snapshot_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("episode identity must be non-empty")
        return value
