"""Canonical V2 State Artifact DTOs shared across post-Retrieval capabilities.

These types are data contracts only. Candidate validation, deterministic policy
checks, and workflow dispositions remain owned by their respective capabilities.
"""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.orchestration.handoff_contracts import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)


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


class AnswerDraftV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    answer: str
    evidence_refs: list[str]


class ReviewIssueV1(TypedDict):
    code: str
    description: str
    action_id: str | None


class ReviewEvidenceGapV1(TypedDict):
    code: str
    description: str
    required_information: list[str]


class ReviewRouteIssueV1(TypedDict):
    code: str
    description: str
    route_id: str | None


class ReviewConfirmationV1(TypedDict):
    reason_code: str
    question: str
    options: list[str]


class ReviewBlockerV1(TypedDict):
    code: str
    description: str


class ReviewPassV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["PASS"]]
    summary: str


class ReviewReviseV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["REVISE"]]
    issues: list[ReviewIssueV1]


class ReviewRetrieveMoreV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["RETRIEVE_MORE"]]
    evidence_gaps: list[ReviewEvidenceGapV1]


class ReviewRouteReconsiderationV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["ROUTE_RECONSIDERATION"]]
    route_issues: list[ReviewRouteIssueV1]


class ReviewConfirmV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["CONFIRM"]]
    confirmation: ReviewConfirmationV1


class ReviewBlockV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["BLOCK"]]
    blockers: list[ReviewBlockerV1]


PlanReviewResultV2 = (
    ReviewPassV2
    | ReviewReviseV2
    | ReviewRetrieveMoreV2
    | ReviewRouteReconsiderationV2
    | ReviewConfirmV2
    | ReviewBlockV2
)


__all__ = [
    "AnswerDraftV2",
    "PlanReviewResultV2",
    "ReviewBlockV2",
    "ReviewBlockerV1",
    "ReviewConfirmV2",
    "ReviewConfirmationV1",
    "ReviewEvidenceGapV1",
    "ReviewIssueV1",
    "ReviewPassV2",
    "ReviewRetrieveMoreV2",
    "ReviewReviseV2",
    "ReviewRouteIssueV1",
    "ReviewRouteReconsiderationV2",
    "WorkAmbiguityV1",
    "WorkAnalysisResultV2",
    "WorkFactV1",
    "WorkRelationV1",
    "WorkRiskV1",
]
