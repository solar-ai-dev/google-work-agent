"""Shared V1 DTOs passed between workflow capabilities."""

from __future__ import annotations

from typing import Literal, NotRequired, Required, TypedDict

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.state_artifact import (
    StateArtifactMetaV1 as StateArtifactMetaV1,
)
from google_work_agent.application.agents.state_artifact import (
    StateArtifactRefV1 as StateArtifactRefV1,
)
from google_work_agent.ports.system.contracts.additional_acquisition import (
    AdditionalAcquisitionRequestV1,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    SemanticAgentOwnerIdV1,
)

SourceName = Literal["GMAIL", "TASKS", "CALENDAR"]
CalendarReadMode = Literal["EVENTS_ONLY", "EVENTS_AND_FREEBUSY"]
TemporalRelation = Literal["RELATIVE", "ABSOLUTE"]
RelativeUnit = Literal["DAY", "WEEK"]
Weekday = Literal["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
Daypart = Literal["MORNING", "AFTERNOON", "EVENING"]
ContextStatusValue = Literal[
    "SUFFICIENT",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "PARTIAL",
    "BLOCKED",
]
SufficiencyIssueTypeValue = Literal["MISSING", "CONFLICT"]
SufficiencyResolutionSourceValue = Literal["USER", "GOOGLE", "POLICY", "ROUTE"]
MissingInformationRequiredForValue = Literal[
    "RETRIEVAL", "ANALYSIS", "PLANNING", "USER_CONFIRMATION"
]
AnalysisStatusValue = Literal[
    "COMPLETE",
    "NEEDS_MORE_DATA",
    "NEEDS_CONFIRMATION",
    "ROUTE_RECONSIDERATION_REQUIRED",
    "BLOCKED",
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
AnswerDraftStatusValue = Literal[
    "ANSWER_ONLY", "NEEDS_CONFIRMATION", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"
]
PlanDraftStatusValue = Literal[
    "PLAN_READY", "NEEDS_CONFIRMATION", "ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"
]
ActionEffectValue = Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]
ReviewStatusValue = Literal[
    "PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"
]
RecheckStatusValue = Literal["PASS", "BLOCK"]
ReviewTargetValue = Literal["ANSWER", "PLAN"]
ConstraintKindValue = Literal[
    "PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"
]


class ClarificationOptionV1(TypedDict):
    option_id: str
    label: str


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
    request_intent: RequestIntentV2 | None
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


class EvidenceRoleDraftV2(TypedDict):
    """docs/05-context-retrieval.md SS5.6 / evidence-selection-result-v2.schema.json.

    Thin reference + classification only -- the LLM never re-supplies
    resource_handle/excerpt/locator; those are joined back from the
    normalized SourceSegment by segment_id (see
    retrieval/select_evidence.py ``materialize_evidence_drafts``)."""

    segment_id: str
    role: Literal["SUPPORTS", "CONTRADICTS", "CONTEXT"]
    relevance_reason: str


class EvidenceSelectionResultV2(TypedDict):
    """docs/05-context-retrieval.md SS5.6 -- retrieval.select_evidence output,
    Retrieval Local State only (RetrievalStateV1.evidence_selection)."""

    schema_version: Required[Literal[2]]
    evidence_drafts: list[EvidenceRoleDraftV2]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]


class SufficiencyIssueV2(TypedDict):
    """docs/05-context-retrieval.md SS19.1 SufficiencyIssue.

    Retrieval's own internal judgment input to the SS19.2 deterministic
    Guard -- not the Parent-facing handoff shape (see MissingInformationV1
    below). The PHASE 7.5 sufficiency-result-v2.schema.json Candidate
    Artifact originally reused MissingInformationV1's
    {code,description,required_for} shape here by mistake (an
    ARTIFACT_CONTRACT_CONFLICT against this exact Canonical section);
    the Candidate schema was corrected to match Canonical instead of
    weakening Canonical to match the mistaken Candidate."""

    slot: str
    issue_type: SufficiencyIssueTypeValue
    required: bool
    resolution_source: SufficiencyResolutionSourceValue
    safety_critical: bool
    reason_codes: list[str]


class SufficiencyResultV2(TypedDict):
    """docs/05-context-retrieval.md SS5.7 -- retrieval.assess_sufficiency
    output, Retrieval Local State only (RetrievalStateV1.sufficiency)."""

    schema_version: Required[Literal[2]]
    status: ContextStatusValue
    issues: list[SufficiencyIssueV2]


class MissingInformationV1(TypedDict):
    """docs/06-agent-workflow.md SS3.3 -- RetrievalResultV1.missing_information
    item. Parent-facing handoff shape, deliberately not the same type as
    SufficiencyIssueV2: a deterministic projection
    (retrieval_sufficiency.missing_information_projection) converts one into
    the other. Full RetrievalResultV1 finalization (wiring this field onto
    the Parent result, renaming coverage/source_statuses/retrieval_rounds)
    is Q2-E scope; this type only prepares the boundary."""

    code: str
    description: str
    required_for: MissingInformationRequiredForValue


class RetrievalSourceStatusV1(TypedDict):
    route_id: str
    resource_type: str
    status: Literal["COMPLETE", "PARTIAL", "FAILED", "NOT_ATTEMPTED"]
    evidence_refs: list[str]
    failure_kind: (
        Literal[
            "AUTH",
            "SCOPE",
            "RATE_LIMIT",
            "TIMEOUT",
            "PROVIDER",
            "NOT_FOUND",
            "BUDGET",
            "OTHER",
        ]
        | None
    )


class RetrievalResultV1(TypedDict):
    """Canonical Retrieval parent handoff (06-agent-workflow.md SS3.3)."""

    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    coverage: Literal["SUFFICIENT", "PARTIAL", "NO_FETCH_NEEDED"]
    context_bundle_ref: str | None
    evidence_refs: list[str]
    selected_segment_ids: list[str]
    excluded_segment_ids: list[str]
    source_resource_refs: list[str]
    source_statuses: list[RetrievalSourceStatusV1]
    availability_results: list[dict[str, object]]
    missing_information: list[MissingInformationV1]
    retrieval_rounds: int


class ConfirmationRequiredV1(TypedDict):
    kind: Required[Literal["CONFIRMATION_REQUIRED"]]
    interrupt_id: str
    semantic_owner_id: SemanticAgentOwnerIdV1
    resume_target: AgentNodeResumeTargetV2
    question: str
    options: list[str]


class RouteReconsiderationRequiredV1(TypedDict):
    kind: Required[Literal["ROUTE_RECONSIDERATION_REQUIRED"]]
    reason_codes: list[str]


class RetrievalNeedV1(TypedDict):
    required_information: str
    reason_codes: list[str]


class RetrievalRequiredV1(TypedDict):
    kind: Required[Literal["RETRIEVAL_REQUIRED"]]
    reason_codes: list[str]
    needs: list[RetrievalNeedV1]


class PlanningRevisionIssueV1(TypedDict):
    dimension: Literal["GOAL_EVIDENCE", "ACTION_SCOPE_ROUTE", "CONSTRAINTS_POLICY"]
    code: str
    description: str
    action_id: str | None
    route_id: str | None


class PlanningRevisionRequiredV1(TypedDict):
    kind: Required[Literal["PLANNING_REVISION_REQUIRED"]]
    destination: Required[Literal["PLANNING"]]
    disposition: Required[Literal["REVISE"]]
    issues: list[PlanningRevisionIssueV1]


class BlockedSignalV1(TypedDict):
    kind: Required[Literal["BLOCKED"]]
    reason_codes: list[str]


WorkflowSignalV1 = (
    ConfirmationRequiredV1
    | RouteReconsiderationRequiredV1
    | RetrievalRequiredV1
    | PlanningRevisionRequiredV1
    | BlockedSignalV1
)


class SubgraphReturnV2[TypedResultT](TypedDict):
    disposition: str
    typed_result: TypedResultT | None
    workflow_signal: WorkflowSignalV1 | None


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
