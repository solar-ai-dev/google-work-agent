"""Owner-local V1 Work Analysis artifact retained for compatibility evaluation."""

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.ports.system.contracts.additional_acquisition import (
    AdditionalAcquisitionRequestV1,
)

AnalysisStatusValue = Literal[
    "COMPLETE", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"
]


AnalysisFindingKind = Literal[
    "FACT",
    "RELATIONSHIP",
    "MISSING_INFORMATION",
    "DUPLICATE_CANDIDATE",
    "CONFLICT",
    "SCHEDULE_RISK",
    "EVIDENCE_GAP",
]


class AnalysisFindingV1(TypedDict):
    schema_version: Required[Literal[1]]
    finding_id: str
    kind: AnalysisFindingKind
    statement: str
    evidence_refs: list[str]
    resource_refs: list[str]
    segment_refs: list[str]
    related_resource_handles: list[str]
    reason_codes: list[str]


class FeasibilityScheduleConstraintsV1(TypedDict):
    business_deadline: str
    business_deadline_source: Literal["USER", "GMAIL_EVIDENCE"]
    expected_duration_minutes: int | None
    duration_source: Literal["EXPLICIT_ESTIMATE", "EVENT_INTERVAL"]


class WorkAnalysisResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: AnalysisStatusValue
    summary: str
    findings: list[AnalysisFindingV1]
    missing_information: list[str]
    confirmation: dict[str, object] | None
    blockers: list[str]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    segment_refs: list[dict[str, object]]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    schedule_constraints: NotRequired[FeasibilityScheduleConstraintsV1]
    llm_provider_result: NotRequired[dict[str, object]]
