"""Closed current Google Workspace fixture snapshot contract."""

from __future__ import annotations

from typing import Literal

from pydantic import JsonValue, field_validator

from evaluation.contracts.evaluation_contract import EvaluationContract


class CurrentFixtureSnapshotV1(EvaluationContract):
    schema_version: Literal[1]
    fixture_snapshot_id: str
    scenario_family_ids: list[str]
    fixture_relation_family: str
    locale: str
    timezone: str
    as_of: str
    permissions: dict[str, JsonValue]
    tool_availability: list[str]
    gmail: dict[str, JsonValue]
    tasks: dict[str, JsonValue]
    calendar: dict[str, JsonValue]
    relations: dict[str, JsonValue]

    @field_validator(
        "fixture_snapshot_id",
        "fixture_relation_family",
        "locale",
        "timezone",
        "as_of",
    )
    @classmethod
    def _require_non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("fixture identity fields must be non-empty")
        return value


__all__ = ["CurrentFixtureSnapshotV1"]
