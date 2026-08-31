"""Current self-contained E2EProjectionV5 contract."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.canonical_case import EndStateGoldV1
from evaluation.contracts.evaluation_contract import EvaluationContract


class E2EProjectionV5(EvaluationContract):
    schema_version: Literal[5]
    case_id: str
    fixture_snapshot_id: str
    product_input: JsonValue
    business_gold: JsonValue
    request_gold: JsonValue
    interaction_gold: JsonValue
    tool_route_gold: JsonValue
    retrieval_gold: JsonValue
    analysis_gold: JsonValue
    planning_gold: JsonValue
    review_gold: JsonValue
    workflow_gold: JsonValue
    safety_gold: JsonValue
    end_state_gold: EndStateGoldV1

    @field_validator("case_id", "fixture_snapshot_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("projection identity must be non-empty")
        return value
