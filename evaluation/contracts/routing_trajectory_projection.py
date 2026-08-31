"""Observed routing trajectory result projection."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


class RoutingTrajectoryProjectionV2(EvaluationContract):
    schema_version: Literal[2]
    case_id: str
    topology_scope: Literal["SINGLE_BASELINE", "THREE_STAGE", "SIX_ROLE_BASELINE"]
    observed_node_ids: list[str]
    observed_tool_ids: list[str]
    skipped_node_ids: list[str]
    budget_snapshot: JsonValue
    diagnostic_only: Literal[True]

    @field_validator("case_id")
    @classmethod
    def _require_identity(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("case_id must be non-empty")
        return value
