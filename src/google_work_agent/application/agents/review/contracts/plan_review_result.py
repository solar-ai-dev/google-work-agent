"""Owner-local Review result contracts."""

from __future__ import annotations

from typing import Literal, Required, TypedDict

from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewDimensionIdV1,
)
from google_work_agent.application.agents.state_artifact import (
    StateArtifactMetaV1,
    StateArtifactRefV1,
)


class ReviewIssueV1(TypedDict):
    code: str
    description: str
    affected_dimensions: list[ReviewDimensionIdV1]
    affected_action_ids: list[str]
    affected_route_ids: list[str]
    evidence_refs: list[str]


class EvidenceGapV1(TypedDict):
    code: str
    description: str
    required_information: list[str]


class RouteIssueV1(TypedDict):
    code: str
    description: str
    affected_route_ids: list[str]


class ReviewConfirmationV1(TypedDict):
    question: str
    options: list[str]


class ReviewBlockerV1(TypedDict):
    code: str
    description: str
    affected_action_ids: list[str]


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
    evidence_gaps: list[EvidenceGapV1]


class ReviewRouteReconsiderationV2(TypedDict):
    schema_version: Required[Literal[2]]
    meta: StateArtifactMetaV1
    status: Required[Literal["ROUTE_RECONSIDERATION"]]
    route_issues: list[RouteIssueV1]


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
    "EvidenceGapV1",
    "PlanReviewResultV2",
    "ReviewBlockV2",
    "ReviewBlockerV1",
    "ReviewConfirmV2",
    "ReviewConfirmationV1",
    "ReviewIssueV1",
    "ReviewPassV2",
    "ReviewRetrieveMoreV2",
    "ReviewReviseV2",
    "ReviewRouteReconsiderationV2",
    "RouteIssueV1",
    "StateArtifactMetaV1",
    "StateArtifactRefV1",
]
