"""Owner-local Review result contracts."""

from __future__ import annotations

from typing import Literal, Required, TypedDict


class StateArtifactRefV1(TypedDict):
    artifact_id: str
    revision: int


class StateArtifactMetaV1(TypedDict):
    artifact_id: str
    revision: int
    based_on: list[StateArtifactRefV1]


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


PlanReviewResultV2 = ReviewPassV2 | ReviewReviseV2 | ReviewRetrieveMoreV2 | ReviewRouteReconsiderationV2 | ReviewConfirmV2 | ReviewBlockV2
