"""Owner-local contracts for Work Analysis."""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.orchestration.handoff_contracts import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)


class WorkFactV1(TypedDict):
    fact_id: str
    kind: Literal[
        "TASK",
        "EVENT",
        "PERSON",
        "DATE",
        "TIME",
        "DEADLINE",
        "STATUS",
        "RESOURCE",
        "TEXT_CLAIM",
        "OTHER",
    ]
    subject: str
    value: str
    derivation: Literal["EXPLICIT", "DERIVED"]
    evidence_refs: list[str]


class WorkRelationV1(TypedDict):
    relation_id: str
    kind: Literal[
        "DEPENDS_ON",
        "ASSIGNED_TO",
        "DUE_AT",
        "DUPLICATES",
        "CONFLICTS_WITH",
        "RELATED_TO",
    ]
    source_fact_id: str
    target_fact_id: str
    evidence_refs: list[str]


class WorkAmbiguityV1(TypedDict):
    code: str
    description: str
    requires_confirmation: bool
    evidence_refs: list[str]


class WorkRiskV1(TypedDict):
    kind: Literal[
        "SCHEDULE_CONFLICT",
        "DEADLINE_RISK",
        "DUPLICATE_RISK",
        "MISSING_INFORMATION",
        "OTHER",
    ]
    severity: Literal["LOW", "MEDIUM", "HIGH"]
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
    action_necessity: Literal["REQUIRED", "NOT_REQUIRED", "UNDETERMINED"]
    action_necessity_reason: str | None
