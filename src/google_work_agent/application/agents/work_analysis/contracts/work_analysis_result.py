"""Owner-local contracts for Work Analysis."""

from __future__ import annotations

from typing import Literal, Required, TypedDict


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]


class WorkFactV1(TypedDict):
    fact_id: str
    fact_type: str
    value: str | list[str]
    evidence_refs: list[str]


class WorkRelationV1(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]
    validator_codes: list[str]


class WorkAmbiguityV1(TypedDict):
    code: str
    description: str
    evidence_refs: list[str]


class WorkRiskV1(TypedDict):
    code: str
    severity: Literal["INFO", "WARNING", "BLOCKING"]
    description: str
    evidence_refs: list[str]


class WorkAnalysisResultV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    work_facts: list[WorkFactV1]
    relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    evidence_refs: list[str]
    policy_confirmation_receipt_refs: list[StateArtifactRefV1]
    action_necessity: Literal["REQUIRED", "NOT_REQUIRED"]
