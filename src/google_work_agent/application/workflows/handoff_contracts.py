"""Shared V1 DTOs passed between workflow capabilities."""

from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.workflows.contracts import AdditionalAcquisitionRequestV1

SourceName = Literal["GMAIL", "TASKS", "CALENDAR"]
CalendarReadMode = Literal["EVENTS_ONLY", "EVENTS_AND_FREEBUSY"]
TemporalRelation = Literal["RELATIVE", "ABSOLUTE"]
RelativeUnit = Literal["DAY", "WEEK"]
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Daypart = Literal["MORNING", "AFTERNOON", "EVENING"]
ContextStatusValue = Literal[
    "SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "PARTIAL", "BLOCKED"
]
AnalysisStatusValue = Literal["COMPLETE", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "BLOCKED"]
AnalysisFindingKind = Literal[
    "FACT",
    "RELATIONSHIP",
    "MISSING_INFORMATION",
    "DUPLICATE_CANDIDATE",
    "CONFLICT",
    "SCHEDULE_RISK",
    "EVIDENCE_GAP",
]
AnswerDraftStatusValue = Literal["ANSWER_ONLY", "NEEDS_CONFIRMATION", "BLOCKED"]
PlanDraftStatusValue = Literal["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
ReviewStatusValue = Literal["PASS", "REVISE", "RETRIEVE_MORE", "CONFIRM", "BLOCK"]
RecheckStatusValue = Literal["PASS", "BLOCK"]
ReviewTargetValue = Literal["ANSWER", "PLAN"]
RequestIntentResponseDispositionValue = Literal["ANSWER_ONLY", "ACTION_REQUIRED"]


class ClarificationOptionV1(TypedDict):
    option_id: str
    label: str


class RequestIntentGoalV1(TypedDict):
    summary: str
    user_visible_objective: str


class RequestIntentTopicConstraintV1(TypedDict):
    text: str
    source_text: str


class RequestIntentPeopleConstraintV1(TypedDict):
    mention: str
    role_hint: str | None
    source_text: str


class RequestIntentTimeConstraintV1(TypedDict):
    mention: str
    granularity_hint: Literal["DATE", "DATETIME", "RANGE", "RELATIVE", "UNKNOWN"]
    source_text: str


class RequestIntentSourceConstraintV1(TypedDict):
    source: Literal["GMAIL", "TASKS", "CALENDAR", "UNKNOWN"]
    mention: str
    confidence: Literal["HIGH", "MEDIUM", "LOW"]


class RequestIntentStatusConstraintV1(TypedDict):
    mention: str
    source_text: str


class RequestIntentSemanticConstraintsV1(TypedDict):
    topics: list[RequestIntentTopicConstraintV1]
    people: list[RequestIntentPeopleConstraintV1]
    time: list[RequestIntentTimeConstraintV1]
    sources: list[RequestIntentSourceConstraintV1]
    status_or_state: list[RequestIntentStatusConstraintV1]
    negative_constraints: list[str]
    policy_or_safety_constraints: list[str]


class RequestIntentAmbiguityItemV1(TypedDict):
    field_path: str
    reason_code: str
    user_question: str


class RequestIntentAmbiguityV1(TypedDict):
    is_ambiguous: bool
    items: list[RequestIntentAmbiguityItemV1]


class RequestIntentUnsupportedScopeV1(TypedDict):
    is_unsupported: bool
    reason_code: str | None
    explanation: str | None


class RequestIntentV1(TypedDict):
    schema_version: Required[Literal[2]]
    goal: RequestIntentGoalV1
    completion_criteria: list[str]
    semantic_constraints: RequestIntentSemanticConstraintsV1
    ambiguity: RequestIntentAmbiguityV1
    unsupported_scope: RequestIntentUnsupportedScopeV1
    response_disposition: NotRequired[RequestIntentResponseDispositionValue]
    requested_effect_hints: NotRequired[list[ActionEffectValue]]
    requested_resource_hints: NotRequired[list[str]]
    analysis_requirement: NotRequired[Literal["NONE", "REQUIRED"]]
    meta: NotRequired[dict[str, object]]


class ClarificationQuestionV1(TypedDict):
    schema_version: Required[Literal[1]]
    origin_target: str
    question: str
    affected_field_paths: list[str]
    reason_code: str
    known_context_summary: str
    options: list[ClarificationOptionV1]


class RequestUnderstandingFailureV1(TypedDict):
    schema_version: Required[Literal[1]]
    reason_code: str
    user_safe_message: str
    diagnostic: str


class RequestUnderstandingOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["COMPLETE", "NEEDS_CONFIRMATION", "INVALID"]
    request_intent: RequestIntentV1 | None
    clarification: ClarificationQuestionV1 | None
    failure: RequestUnderstandingFailureV1 | None
    validator_codes: list[str]
    llm_provider_result: NotRequired[dict[str, object]]


class TemporalQueryV1(TypedDict):
    schema_version: Required[Literal[1]]
    relation: TemporalRelation
    relative_unit: RelativeUnit | None
    relative_offset: int | None
    weekday: Weekday | None
    daypart: Daypart | None
    absolute_start: str | None
    absolute_end: str | None


class SourceFetchPlanV1(TypedDict):
    schema_version: Required[Literal[2]]
    source: SourceName
    priority: int
    reason_codes: list[str]
    constraints: dict[str, object]
    page_size: int
    max_pages: int
    max_candidates: int
    detail_limit: int
    required: bool
    calendar_read_mode: CalendarReadMode | None
    temporal_query: TemporalQueryV1 | None


class SourcePlanningOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["PLAN_READY", "NO_FETCH_NEEDED", "NEEDS_CONFIRMATION", "BLOCKED"]
    source_fetch_plans: list[SourceFetchPlanV1]
    clarification: dict[str, object] | None
    failure: dict[str, object] | None
    validator_codes: list[str]
    llm_provider_result: dict[str, object]


class AcquisitionResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: Literal[
        "COMPLETE", "PARTIAL", "AUTH_REQUIRED", "RATE_LIMITED", "BUDGET_EXHAUSTED", "FAILED"
    ]
    resource_handles: list[str]
    source_summaries: list[dict[str, object]]
    missing_slots: list[str]
    remaining_budget: dict[str, int]


class EvidenceDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    evidence_id: str
    resource_handle: str
    segment_id: str
    kind: str
    excerpt: str
    locator: dict[str, object] | None
    reason_codes: list[str]


class ContextBundleV1(TypedDict):
    schema_version: Required[Literal[1]]
    resource_refs: list[dict[str, object]]
    segment_refs: list[dict[str, object]]
    evidence_refs: list[str]
    normalized_context: list[dict[str, object]]
    missing_information: list[str]
    ambiguity: dict[str, object] | None


class ContextRetrievalResultV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: ContextStatusValue
    context_bundle: ContextBundleV1
    evidence_drafts: list[EvidenceDraftV1]
    selected_segment_ids: list[str]
    excluded_resource_handles: list[str]
    missing_slots: list[str]
    additional_acquisition_request: AdditionalAcquisitionRequestV1 | None
    sufficiency: dict[str, object]
    llm_provider_result: NotRequired[dict[str, object]]


class EvidenceSelectionOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    result: Literal["SELECTED", "PARTIAL", "BLOCKED"]
    selected_segment_ids: list[str]
    evidence_drafts: list[EvidenceDraftV1]
    excluded_resource_handles: list[str]
    missing_information: list[str]
    ambiguity: dict[str, object] | None


class SufficiencyOutputV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: ContextStatusValue
    sufficiency: dict[str, object]
    missing_slots: list[str]
    ambiguity: dict[str, object] | None


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


class AnswerDraftV1(TypedDict):
    schema_version: Required[Literal[1]]
    status: AnswerDraftStatusValue
    answer: str
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    reason_codes: list[str]
    confirmation: dict[str, object] | None
    blockers: list[str]
    llm_provider_result: NotRequired[dict[str, object]]


class ActionDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    action_id: str
    position: int
    effect: ActionEffectValue
    tool_name: str
    arguments: dict[str, object]
    expected: dict[str, object]
    evidence_refs: list[str]
    resource_refs: list[str]
    target_resource_ref_id: str | None
    depends_on_action_ids: list[str]
    user_visible_reason: str


class ActionPlanDraftV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: PlanDraftStatusValue
    plan_id: str
    summary: str
    objective: str
    actions: list[ActionDraftV1]
    evidence_refs: list[str]
    resource_refs: list[dict[str, object]]
    confirmation: dict[str, object] | None
    llm_provider_result: NotRequired[dict[str, object]]


class ReviewIssueV1(TypedDict):
    schema_version: Required[Literal[2]]
    issue_id: str
    kind: str
    message: str
    affected_action_ids: list[str]
    affected_field_paths: list[str]
    evidence_refs: list[str]
    resource_refs: list[str]
    reason_codes: list[str]


class PlanReviewResultV1(TypedDict):
    schema_version: Required[Literal[2]]
    status: ReviewStatusValue
    summary: str
    issues: list[ReviewIssueV1]
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
