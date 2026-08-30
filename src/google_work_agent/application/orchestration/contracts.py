"""Workflow contracts taken from the agent workflow design document."""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Literal, NotRequired, Required, TypedDict, cast

from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RunBudgetV2,
)

# ``handoff_contracts`` imports this module for shared budget types.  Keep the
# runtime annotation resolvable without creating that reverse import cycle;
# static checking still sees the exact union below.
if TYPE_CHECKING:
    from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
        ScopeExpansionRequiredV1,
        ToolRoutePlanV2,
    )
    from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
        WorkAnalysisResultV2,
    )
    from google_work_agent.application.orchestration.handoff_contracts import (
        AcquisitionResultV1,
        ActionPlanDraftV1,
        AnswerDraftV1,
        ContextRetrievalResultV1,
        RequestIntentV2,
        RetrievalResultV1,
        SourceFetchPlanV1,
        StateArtifactMetaV1,
        WorkflowSignalV1,
    )
else:
    WorkflowSignalV1 = object


class MultiAgentGraphState(TypedDict):
    """Typed state fields defined by `docs/06-agent-workflow.md` section 3."""

    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: WorkflowSignalV1 | ScopeExpansionRequiredV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    context_result: ContextRetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    approved_plan_id: str | None
    execution_summary: dict[str, object] | None
    verification_summary: dict[str, object] | None
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]


class GraphStateUpdateV1(TypedDict, total=False):
    """Typed partial update returned by workflow agents and the supervisor."""

    workflow_phase: str
    request_intent: RequestIntentV2 | None
    tool_route_plan: ToolRoutePlanV2 | None
    workflow_signal: WorkflowSignalV1 | ScopeExpansionRequiredV1 | None
    source_fetch_plans: list[SourceFetchPlanV1]
    acquisition_result: AcquisitionResultV1 | None
    retrieval_result: RetrievalResultV1 | None
    context_result: ContextRetrievalResultV1 | None
    work_analysis_result: WorkAnalysisResultV2 | None
    answer_draft: AnswerDraftV1 | None
    plan_draft: ActionPlanDraftV1 | None
    plan_review: PlanReviewResultV2 | None
    approved_plan_id: str | None
    execution_summary: dict[str, object] | None
    verification_summary: dict[str, object] | None
    finalize_intent: FinalizeIntentV1 | None
    user_interrupt: UserInterruptV1 | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]
    retry_budget: RunBudgetV2
    prompt_context: dict[str, object]
    trace_context: dict[str, object]


class WorkflowPhase(StrEnum):
    """Workflow phase values defined by `docs/06-agent-workflow.md` section 4."""

    INITIALIZE = "INITIALIZE"
    REQUEST_ANALYSIS = "REQUEST_ANALYSIS"
    TOOL_ROUTING = "TOOL_ROUTING"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    SOURCE_PLANNING = "SOURCE_PLANNING"
    API_ACQUISITION = "API_ACQUISITION"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    CONTEXT_EVALUATION = "CONTEXT_EVALUATION"
    WORK_ANALYSIS = "WORK_ANALYSIS"
    SOLUTION_PLANNING = "SOLUTION_PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREFLIGHT = "PREFLIGHT"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    VERIFICATION = "VERIFICATION"
    RESPONSE_SYNTHESIS = "RESPONSE_SYNTHESIS"
    RECOVERY = "RECOVERY"
    FINALIZE = "FINALIZE"


class RequestUnderstandingResult(StrEnum):
    """Request-understanding node results."""

    COMPLETE = "COMPLETE"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    INVALID = "INVALID"


class ApiPlanningResult(StrEnum):
    """API planning node results."""

    PLAN_READY = "PLAN_READY"
    NO_FETCH_NEEDED = "NO_FETCH_NEEDED"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    BLOCKED = "BLOCKED"


class ApiAcquisitionResult(StrEnum):
    """API acquisition node results."""

    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
    FAILED = "FAILED"


class ContextResult(StrEnum):
    """Context node results."""

    SUFFICIENT = "SUFFICIENT"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class AnalysisResult(StrEnum):
    """Analysis node results."""

    COMPLETE = "COMPLETE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    BLOCKED = "BLOCKED"


class PlanningResult(StrEnum):
    """Planning node results."""

    ANSWER_ONLY = "ANSWER_ONLY"
    PLAN_READY = "PLAN_READY"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    ROUTE_RECONSIDERATION_REQUIRED = "ROUTE_RECONSIDERATION_REQUIRED"
    BLOCKED = "BLOCKED"


class ReviewResult(StrEnum):
    """Review node results."""

    PASS = "PASS"
    REVISE = "REVISE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
    ROUTE_RECONSIDERATION = "ROUTE_RECONSIDERATION"
    CONFIRM = "CONFIRM"
    BLOCK = "BLOCK"


class FinalizeIntent(StrEnum):
    """Deterministic terminal intents handed off to Stage 16."""

    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class DomainValidationResult(StrEnum):
    """Domain-validation node results."""

    ALLOW_READ = "ALLOW_READ"
    REQUIRE_APPROVAL = "REQUIRE_APPROVAL"
    BLOCK = "BLOCK"


class DomainValidationOutputV1(TypedDict):
    """Deterministic domain-validation output consumed by the workflow boundary."""

    schema_version: Required[Literal[1]]
    result: Literal["ALLOW_READ", "REQUIRE_APPROVAL", "BLOCK"]
    reason_codes: list[str]
    blocked_action_ids: list[str]


class ConfirmationResponseKind(StrEnum):
    """Typed confirmation response kinds carried through the resume boundary."""

    OPTION = "OPTION"
    FREE_TEXT = "FREE_TEXT"
    DECLINE = "DECLINE"


class AdditionalAcquisitionOriginResult(StrEnum):
    """Structured retrieval-redirection results understood by the supervisor."""

    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    RETRIEVE_MORE = "RETRIEVE_MORE"


class AdditionalAcquisitionRequestV1(TypedDict):
    """Structured request for another Stage 5 source-planning round."""

    schema_version: Required[Literal[1]]
    origin_phase: str
    origin_result: str
    missing_slots: list[str]
    missing_information: list[str]
    evidence_refs: list[str]
    reason_codes: list[str]


class ConfirmationResponseProjectionV1(TypedDict):
    """Bounded response projected to the resumed semantic owner."""

    schema_version: Required[Literal[1]]
    response_kind: Literal["OPTION", "FREE_TEXT", "DECLINE"]
    selected_option: str | None
    free_text: str | None


class UserInterruptOptionV1(TypedDict):
    """Checkpoint-safe clarification option projection persisted in `user_interrupt`."""

    option_id: str
    label: str


class UserInterruptV1(TypedDict):
    """Checkpoint-safe confirmation interrupt payload owned by the supervisor."""

    schema_version: Required[Literal[1]]
    interrupt_kind: Literal["CONFIRMATION"]
    resume_kind: Literal["CONFIRMATION"]
    origin_target: str
    question: str
    affected_field_paths: list[str]
    reason_code: str
    known_context_summary: str
    options: list[UserInterruptOptionV1]


class PolicyConfirmationReceiptV1(TypedDict):
    """Immutable proof that a real, validated user response resolved one
    SCOPE_EXPANSION/DUPLICATE_OVERRIDE/CONFLICT_OVERRIDE Confirmation
    (06-agent-workflow.md SS3.7 PolicyConfirmationReceiptV1). LLM/Agent code
    never constructs this -- only the Application/Confirmation Controller
    layer does, from an already-validated ConfirmationResponseProjectionV1.
    ``decision_context_hash`` binds the receipt to the exact scope-expansion
    request content it answered, so a stale or forged receipt fails closed
    when re-verified against different content.
    """

    schema_version: Required[Literal[1]]
    meta: StateArtifactMetaV1
    interrupt_id: str
    confirmation_kind: Literal["SCOPE_EXPANSION", "DUPLICATE_OVERRIDE", "CONFLICT_OVERRIDE"]
    decision: Literal["APPROVED", "DECLINED"]
    semantic_owner_id: Literal["TOOL_ROUTE", "WORK_ANALYSIS"]
    decision_context_hash: str
    affected_route_ids: list[str]
    affected_resource_refs: list[str]


class FinalizeIntentV1(TypedDict):
    """Checkpoint-safe finalize handoff consumed by Stage 16."""

    schema_version: Required[Literal[1]]
    intent: Literal["COMPLETED", "BLOCKED", "FAILED"]
    reason_code: str
    result_kind: NotRequired[Literal["PARTIAL"] | None]


class PromptSelectionKey(TypedDict):
    """Prompt selection key fields defined by `docs/06-agent-workflow.md` section 7."""

    agent_role: str
    subgraph_name: str
    node_name: str
    node_state: str
    purpose: str
    input_schema_version: str
    output_schema_version: str


class PromptRef(TypedDict):
    """Prompt reference fields defined by `docs/06-agent-workflow.md` section 7."""

    prompt_bundle_version: str
    prompt_id: str
    prompt_version: str
    content_hash: str
    agent_role: str
    subgraph_name: str
    node_name: str
    node_state: str
    purpose: str
    input_schema_version: str
    output_schema_version: str


class AgentFailureRecordV1(TypedDict):
    """Invocation-local failure scratch owned by one native agent subgraph."""

    schema_version: Required[Literal[1]]
    reason_code: str
    diagnostic: str | None
    retryable: bool


class AgentDispositionV1(TypedDict):
    """Invocation-local disposition returned by one native agent subgraph."""

    schema_version: Required[Literal[1]]
    status: str
    next_target: str | None
    reason_code: str | None


class AgentLocalStateV1(TypedDict):
    """Canonical invocation-local state for one native agent subgraph."""

    schema_version: Required[Literal[1]]
    agent_role: str
    invocation_id: str
    node_state: str
    input_projection: dict[str, object]
    candidate_output: dict[str, object] | None
    prompt_ref: PromptRef | None
    attempt_no: int
    schema_repair_count: int
    semantic_revision_count: int
    failure_record: AgentFailureRecordV1 | None
    disposition: AgentDispositionV1 | None
    typed_result: dict[str, object] | None


class _LlmProviderResultRequired(TypedDict):
    structured_output: dict[str, object]
    provider: str
    model: str
    actual_runtime: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


class LlmProviderResult(_LlmProviderResultRequired, total=False):
    """LLM provider result metadata from `docs/07-tool-mcp-internal-interface.md` section 18."""

    fallback_reason: str


ADDITIONAL_ACQUISITION_ALLOWED_PHASES = frozenset(
    {
        WorkflowPhase.CONTEXT_EVALUATION.value,
        WorkflowPhase.WORK_ANALYSIS.value,
        WorkflowPhase.PLAN_REVIEW.value,
    }
)
ADDITIONAL_ACQUISITION_ALLOWED_RESULTS = frozenset(
    item.value for item in AdditionalAcquisitionOriginResult
)
CONFIRMATION_RESPONSE_ALLOWED_KINDS = frozenset(item.value for item in ConfirmationResponseKind)
CONFIRMATION_ORIGIN_TARGETS = frozenset(
    {
        "request.detect_ambiguity",
        "tool_route.finalize",
        "acquisition.plan_sources",
        "retrieval.assess_sufficiency",
        "analysis.assess_information_gaps",
        "analysis.assess_operational_risks",
        "planning.outline_answer",
        "planning.compose_arguments_per_output_route",
        "review.aggregate_findings",
    }
)
CONFIRMATION_RESUME_KIND = "CONFIRMATION"


MULTI_AGENT_GRAPH_STATE_FIELDS = frozenset(MultiAgentGraphState.__annotations__)
PROMPT_SELECTION_KEY_FIELDS = frozenset(PromptSelectionKey.__annotations__)
PROMPT_REF_FIELDS = frozenset(PromptRef.__annotations__)
AGENT_LOCAL_STATE_FIELDS = frozenset(AgentLocalStateV1.__annotations__)
LLM_PROVIDER_RESULT_FIELDS = frozenset(LlmProviderResult.__annotations__)
LLM_PROVIDER_RESULT_REQUIRED_FIELDS = frozenset(LlmProviderResult.__required_keys__)
LLM_PROVIDER_RESULT_OPTIONAL_FIELDS = frozenset(LlmProviderResult.__optional_keys__)


def validate_additional_acquisition_request_v1(
    value: object,
    *,
    allowed_evidence_refs: set[str] | None = None,
) -> AdditionalAcquisitionRequestV1:
    if not isinstance(value, dict):
        raise ValueError("additional acquisition request must be an object")
    required = {
        "schema_version",
        "origin_phase",
        "origin_result",
        "missing_slots",
        "missing_information",
        "evidence_refs",
        "reason_codes",
    }
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(
            f"additional acquisition request missing required fields: {sorted(missing)}"
        )
    if extra:
        raise ValueError(f"additional acquisition request has unsupported fields: {sorted(extra)}")
    schema_version = value["schema_version"]
    if schema_version != 1:
        raise ValueError("additional acquisition request schema_version must be 1")
    origin_phase = _require_string(value["origin_phase"], "origin_phase")
    if origin_phase not in ADDITIONAL_ACQUISITION_ALLOWED_PHASES:
        raise ValueError("additional acquisition request origin_phase is invalid")
    origin_result = _require_string(value["origin_result"], "origin_result")
    if origin_result not in ADDITIONAL_ACQUISITION_ALLOWED_RESULTS:
        raise ValueError("additional acquisition request origin_result is invalid")
    evidence_refs = _require_string_list(value["evidence_refs"], "evidence_refs")
    missing_slots = _require_string_list(value["missing_slots"], "missing_slots")
    missing_information = _require_string_list(
        value["missing_information"],
        "missing_information",
    )
    reason_codes = _require_string_list(value["reason_codes"], "reason_codes")
    if not (missing_slots or missing_information or reason_codes):
        raise ValueError(
            "additional acquisition request requires at least one of missing_slots, "
            "missing_information, or reason_codes"
        )
    if allowed_evidence_refs is not None:
        for evidence_ref in evidence_refs:
            if evidence_ref not in allowed_evidence_refs:
                raise ValueError(
                    "additional acquisition request evidence reference does not exist: "
                    f"{evidence_ref}"
                )
    return {
        "schema_version": 1,
        "origin_phase": origin_phase,
        "origin_result": origin_result,
        "missing_slots": missing_slots,
        "missing_information": missing_information,
        "evidence_refs": evidence_refs,
        "reason_codes": reason_codes,
    }


def validate_domain_validation_output_v1(value: object) -> DomainValidationOutputV1:
    if not isinstance(value, dict):
        raise ValueError("domain validation output must be an object")
    required = {"schema_version", "result", "reason_codes", "blocked_action_ids"}
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"domain validation output missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"domain validation output has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 1:
        raise ValueError("domain validation output schema_version must be 1")
    result = _require_string(value["result"], "result")
    if result not in {item.value for item in DomainValidationResult}:
        raise ValueError("domain validation output result is invalid")
    reason_codes = _require_general_string_list(value["reason_codes"], "reason_codes")
    blocked_action_ids = _require_general_string_list(
        value["blocked_action_ids"],
        "blocked_action_ids",
    )
    return {
        "schema_version": 1,
        "result": cast(Literal["ALLOW_READ", "REQUIRE_APPROVAL", "BLOCK"], result),
        "reason_codes": reason_codes,
        "blocked_action_ids": blocked_action_ids,
    }


def validate_confirmation_origin_target(value: object) -> str:
    target = _require_string(value, "origin_target")
    if target not in CONFIRMATION_ORIGIN_TARGETS:
        raise ValueError("confirmation origin_target is invalid")
    return target


def validate_confirmation_response_projection_v1(
    value: object,
) -> ConfirmationResponseProjectionV1:
    if not isinstance(value, dict):
        raise ValueError("confirmation response must be an object")
    required = {"schema_version", "response_kind", "selected_option", "free_text"}
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"confirmation response missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"confirmation response has unsupported fields: {sorted(extra)}")
    schema_version = value["schema_version"]
    if schema_version != 1:
        raise ValueError("confirmation response schema_version must be 1")
    response_kind = _require_string(value["response_kind"], "response_kind")
    if response_kind not in CONFIRMATION_RESPONSE_ALLOWED_KINDS:
        raise ValueError("confirmation response response_kind is invalid")
    selected_option = value["selected_option"]
    if selected_option is not None and (
        not isinstance(selected_option, str) or not selected_option
    ):
        raise ValueError("confirmation response selected_option must be non-empty or null")
    free_text = value["free_text"]
    if free_text is not None and not isinstance(free_text, str):
        raise ValueError("confirmation response free_text must be a string or null")
    normalized_free_text = None if free_text is None else free_text.strip()
    if response_kind == ConfirmationResponseKind.OPTION.value:
        if selected_option is None:
            raise ValueError("OPTION requires selected_option")
        if normalized_free_text:
            raise ValueError("OPTION must not include free_text")
        normalized_free_text = None
    elif response_kind == ConfirmationResponseKind.FREE_TEXT.value:
        if selected_option is not None:
            raise ValueError("FREE_TEXT must not include selected_option")
        if not normalized_free_text:
            raise ValueError("FREE_TEXT requires non-empty free_text")
    else:
        if selected_option is not None or normalized_free_text:
            raise ValueError("DECLINE must not include response payload fields")
        normalized_free_text = None
    return {
        "schema_version": 1,
        "response_kind": cast(Literal["OPTION", "FREE_TEXT", "DECLINE"], response_kind),
        "selected_option": selected_option,
        "free_text": normalized_free_text,
    }


def validate_user_interrupt_v1(value: object) -> UserInterruptV1:
    if not isinstance(value, dict):
        raise ValueError("user interrupt must be an object")
    required = {
        "schema_version",
        "interrupt_kind",
        "resume_kind",
        "origin_target",
        "question",
        "affected_field_paths",
        "reason_code",
        "known_context_summary",
        "options",
    }
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"user interrupt missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"user interrupt has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 1:
        raise ValueError("user interrupt schema_version must be 1")
    interrupt_kind = _require_string(value["interrupt_kind"], "interrupt_kind")
    if interrupt_kind != "CONFIRMATION":
        raise ValueError("user interrupt interrupt_kind is invalid")
    resume_kind = _require_string(value["resume_kind"], "resume_kind")
    if resume_kind != CONFIRMATION_RESUME_KIND:
        raise ValueError("user interrupt resume_kind is invalid")
    options: list[UserInterruptOptionV1] = []
    seen_option_ids: set[str] = set()
    raw_options = value["options"]
    if not isinstance(raw_options, list):
        raise ValueError("user interrupt options must be a list")
    for index, item in enumerate(raw_options):
        if not isinstance(item, dict):
            raise ValueError(f"user interrupt options[{index}] must be an object")
        option_keys = set(item)
        if option_keys != {"option_id", "label"}:
            raise ValueError("user interrupt option has unsupported fields")
        option_id = _require_non_empty_string(
            item["option_id"],
            f"options[{index}].option_id",
            "user interrupt",
        )
        if option_id in seen_option_ids:
            raise ValueError(f"duplicate user interrupt option_id: {option_id}")
        seen_option_ids.add(option_id)
        options.append(
            {
                "option_id": option_id,
                "label": _require_non_empty_string(
                    item["label"],
                    f"options[{index}].label",
                    "user interrupt",
                ),
            }
        )
    return {
        "schema_version": 1,
        "interrupt_kind": cast(Literal["CONFIRMATION"], interrupt_kind),
        "resume_kind": cast(Literal["CONFIRMATION"], resume_kind),
        "origin_target": validate_confirmation_origin_target(value["origin_target"]),
        "question": _require_non_empty_string(value["question"], "question", "user interrupt"),
        "affected_field_paths": _require_string_list(
            value["affected_field_paths"],
            "affected_field_paths",
        ),
        "reason_code": _require_non_empty_string(
            value["reason_code"],
            "reason_code",
            "user interrupt",
        ),
        "known_context_summary": _require_non_empty_string(
            value["known_context_summary"],
            "known_context_summary",
            "user interrupt",
        ),
        "options": options,
    }


def validate_finalize_intent_v1(value: object) -> FinalizeIntentV1:
    if not isinstance(value, dict):
        raise ValueError("finalize intent must be an object")
    required = {"schema_version", "intent", "reason_code"}
    optional = {"result_kind"}
    actual = set(value)
    missing = required - actual
    extra = actual - required - optional
    if missing:
        raise ValueError(f"finalize intent missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"finalize intent has unsupported fields: {sorted(extra)}")
    schema_version = value["schema_version"]
    if schema_version != 1:
        raise ValueError("finalize intent schema_version must be 1")
    intent = _require_non_empty_string(value["intent"], "intent", "finalize intent")
    if intent not in {item.value for item in FinalizeIntent}:
        raise ValueError("finalize intent intent is invalid")
    reason_code = _require_non_empty_string(value["reason_code"], "reason_code", "finalize intent")
    result_kind = value.get("result_kind")
    if result_kind is not None and result_kind != "PARTIAL":
        raise ValueError("finalize intent result_kind must be PARTIAL or null")
    return {
        "schema_version": 1,
        "intent": cast(Literal["COMPLETED", "BLOCKED", "FAILED"], intent),
        "reason_code": reason_code,
        "result_kind": cast(Literal["PARTIAL"] | None, result_kind),
    }


def _require_string(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"additional acquisition request {field_name} must be a string")
    return value


def _require_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"additional acquisition request {field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(
                f"additional acquisition request {field_name}[{index}] must be a string"
            )
        result.append(item)
    return result


def _require_general_string_list(value: object, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ValueError(f"{field_name}[{index}] must be a string")
        result.append(item)
    return result


def _require_non_empty_string(value: object, field_name: str, context: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{context} {field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{context} {field_name} must be non-empty")
    return normalized


def _canonical_string_list(
    value: object,
    field_name: str,
    *,
    context: str,
    allow_empty: bool,
    unique: bool,
    sort_values: bool,
) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{context} {field_name} must be a list")
    result: list[str] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        normalized = _require_non_empty_string(item, f"{field_name}[{index}]", context)
        if unique:
            if normalized in seen:
                continue
            seen.add(normalized)
        result.append(normalized)
    if not allow_empty and not result:
        raise ValueError(f"{context} {field_name} must not be empty")
    if sort_values:
        result.sort()
    return result


def _require_non_negative_int(value: object, field_name: str, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} {field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{context} {field_name} must be non-negative")
    return value


def _require_positive_int(value: object, field_name: str, context: str) -> int:
    if not isinstance(value, int):
        raise ValueError(f"{context} {field_name} must be an integer")
    if value <= 0:
        raise ValueError(f"{context} {field_name} must be positive")
    return value


__all__ = [
    "ADDITIONAL_ACQUISITION_ALLOWED_PHASES",
    "ADDITIONAL_ACQUISITION_ALLOWED_RESULTS",
    "AdditionalAcquisitionOriginResult",
    "AdditionalAcquisitionRequestV1",
    "CONFIRMATION_ORIGIN_TARGETS",
    "CONFIRMATION_RESUME_KIND",
    "CONFIRMATION_RESPONSE_ALLOWED_KINDS",
    "AnalysisResult",
    "ApiAcquisitionResult",
    "ApiPlanningResult",
    "ConfirmationResponseKind",
    "ConfirmationResponseProjectionV1",
    "ContextResult",
    "DomainValidationResult",
    "DomainValidationOutputV1",
    "FinalizeIntent",
    "FinalizeIntentV1",
    "GraphStateUpdateV1",
    "LLM_PROVIDER_RESULT_FIELDS",
    "LLM_PROVIDER_RESULT_OPTIONAL_FIELDS",
    "LLM_PROVIDER_RESULT_REQUIRED_FIELDS",
    "LlmProviderResult",
    "MULTI_AGENT_GRAPH_STATE_FIELDS",
    "MultiAgentGraphState",
    "PROMPT_REF_FIELDS",
    "PROMPT_SELECTION_KEY_FIELDS",
    "PlanningResult",
    "PromptRef",
    "PromptSelectionKey",
    "RequestUnderstandingResult",
    "ReviewResult",
    "RunBudgetV2",
    "validate_confirmation_origin_target",
    "validate_confirmation_response_projection_v1",
    "validate_finalize_intent_v1",
    "validate_additional_acquisition_request_v1",
    "validate_domain_validation_output_v1",
    "WorkflowPhase",
]
