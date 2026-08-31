"""Owner-local V1 Review artifacts used by compatibility evaluation."""

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.ports.system.contracts.additional_acquisition import (
    AdditionalAcquisitionRequestV1,
)

ReviewStatusValue = Literal[
    "PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"
]


RecheckStatusValue = Literal["PASS", "BLOCK"]


ReviewTargetValue = Literal["ANSWER", "PLAN"]


ConstraintKindValue = Literal[
    "PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"
]


class LegacyPlanReviewIssueV1(TypedDict):
    schema_version: Required[Literal[2]]
    issue_id: str
    kind: str
    message: str
    affected_action_ids: list[str]
    affected_field_paths: list[str]
    evidence_refs: list[str]
    resource_refs: list[str]
    reason_codes: list[str]


ReviewIssueV1 = LegacyPlanReviewIssueV1


class PlanReviewResultV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: ReviewStatusValue
    summary: str
    issues: list[LegacyPlanReviewIssueV1]
    confirmation: dict[str, object] | None
    blockers: list[str]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    llm_provider_result: NotRequired[dict[str, object]]


class ToolPolicySummaryV1(TypedDict):
    tool_name: str
    effect_type: str
    approval_requirement: str
    verification_policy: str
    recovery_policy: str
    scope: str
    retryable: bool
    input_schema_version: str
    output_schema_version: str
    registry_version: str
    tool_schema_hash: str


class EvidencePolicySummaryV1(TypedDict):
    minimum_evidence_per_action: int
    update_targeting_requirements: list[str]


class PolicyReviewContextV1(TypedDict):
    schema_version: Required[Literal[1]]
    tool_registry_version: str
    tool_policies: list[ToolPolicySummaryV1]
    evidence_policy: EvidencePolicySummaryV1
