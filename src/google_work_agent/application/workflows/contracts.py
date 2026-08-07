"""Workflow contracts taken from the agent workflow design document."""

from enum import StrEnum
from typing import Literal, NotRequired, Required, TypedDict, cast


class BudgetProfile(StrEnum):
    """Typed run budget profiles frozen by the Stage 10 Gap C contract."""

    NORMAL = "NORMAL"
    REVISION_HEAVY = "REVISION_HEAVY"
    RETRIEVAL_HEAVY = "RETRIEVAL_HEAVY"


class BudgetDecision(StrEnum):
    """Deterministic budget gate result."""

    ALLOW = "ALLOW"
    DENY = "DENY"


class BudgetReasonCode(StrEnum):
    """Structured denial reasons owned by the budget subsystem."""

    PROFILE_LLM_LIMIT_EXHAUSTED = "PROFILE_LLM_LIMIT_EXHAUSTED"
    ABSOLUTE_LLM_LIMIT_EXHAUSTED = "ABSOLUTE_LLM_LIMIT_EXHAUSTED"
    ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED = "ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED"
    PLANNING_REVISION_LIMIT_EXHAUSTED = "PLANNING_REVISION_LIMIT_EXHAUSTED"
    REVIEW_RECHECK_LIMIT_EXHAUSTED = "REVIEW_RECHECK_LIMIT_EXHAUSTED"
    SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED = "SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED"


SCHEMA_REPAIR_PER_NODE_CALL = 1
SEMANTIC_REVISION_SAME_FAILURE = 1
PLANNING_REVISION_PER_RUN = 2
REVIEW_RECHECK_PER_PLANNING_REVISION = 1
MAX_ADDITIONAL_ACQUISITIONS = 2

NORMAL_MAX_LLM_CALLS = 8
REVISION_HEAVY_MAX_LLM_CALLS = 12
RETRIEVAL_HEAVY_MAX_LLM_CALLS = 14
ABSOLUTE_MAX_LLM_CALLS = 16


class SemanticFailureSignatureV1(TypedDict):
    """Canonical same-failure signature used by semantic revision gates."""

    schema_version: Required[Literal[1]]
    node_id: str
    failure_reason_codes: list[str]


class RunBudgetV1(TypedDict):
    """Checkpoint-safe per-run budget state."""

    schema_version: Required[Literal[1]]
    profile: Literal["NORMAL", "REVISION_HEAVY", "RETRIEVAL_HEAVY"]
    llm_calls_used: int
    additional_acquisitions_used: int
    planning_revisions_used: int
    last_rechecked_planning_revision: int
    semantic_revision_signatures_used: list[SemanticFailureSignatureV1]


class BudgetDecisionV1(TypedDict):
    """Minimal structured response returned by deterministic budget helpers."""

    schema_version: Required[Literal[1]]
    decision: Literal["ALLOW", "DENY"]
    budget_reason_code: (
        Literal[
            "PROFILE_LLM_LIMIT_EXHAUSTED",
            "ABSOLUTE_LLM_LIMIT_EXHAUSTED",
            "ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED",
            "PLANNING_REVISION_LIMIT_EXHAUSTED",
            "REVIEW_RECHECK_LIMIT_EXHAUSTED",
            "SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED",
        ]
        | None
    )
    run_budget: RunBudgetV1


BUDGET_PROFILE_LIMITS = {
    BudgetProfile.NORMAL: NORMAL_MAX_LLM_CALLS,
    BudgetProfile.REVISION_HEAVY: REVISION_HEAVY_MAX_LLM_CALLS,
    BudgetProfile.RETRIEVAL_HEAVY: RETRIEVAL_HEAVY_MAX_LLM_CALLS,
}
_BUDGET_PROFILE_ORDER = {
    BudgetProfile.NORMAL: 0,
    BudgetProfile.REVISION_HEAVY: 1,
    BudgetProfile.RETRIEVAL_HEAVY: 2,
}


class MultiAgentGraphState(TypedDict):
    """Typed state fields defined by `docs/06-agent-workflow.md` section 3."""

    schema_version: int
    run_id: str
    conversation_id: str
    thread_id: str
    workflow_phase: str
    request_intent: dict[str, object] | None
    source_fetch_plans: list[dict[str, object]]
    acquisition_result: dict[str, object] | None
    context_result: dict[str, object] | None
    analysis_result: dict[str, object] | None
    answer_draft: dict[str, object] | None
    plan_draft: dict[str, object] | None
    plan_review: dict[str, object] | None
    approved_plan_id: str | None
    execution_summary: dict[str, object] | None
    verification_summary: dict[str, object] | None
    finalize_intent: "FinalizeIntentV1 | None"
    user_interrupt: "UserInterruptV1 | None"
    retry_budget: RunBudgetV1
    prompt_context: dict[str, object]
    trace_context: dict[str, object]


class WorkflowPhase(StrEnum):
    """Workflow phase values defined by `docs/06-agent-workflow.md` section 4."""

    INITIALIZE = "INITIALIZE"
    REQUEST_ANALYSIS = "REQUEST_ANALYSIS"
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
    PARTIAL = "PARTIAL"
    BLOCKED = "BLOCKED"


class AnalysisResult(StrEnum):
    """Analysis node results."""

    COMPLETE = "COMPLETE"
    NEEDS_MORE_DATA = "NEEDS_MORE_DATA"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    BLOCKED = "BLOCKED"


class PlanningResult(StrEnum):
    """Planning node results."""

    ANSWER_ONLY = "ANSWER_ONLY"
    PLAN_READY = "PLAN_READY"
    NEEDS_CONFIRMATION = "NEEDS_CONFIRMATION"
    BLOCKED = "BLOCKED"


class ReviewResult(StrEnum):
    """Review node results."""

    PASS = "PASS"
    REVISE = "REVISE"
    RETRIEVE_MORE = "RETRIEVE_MORE"
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


class ConfirmationResponseKind(StrEnum):
    """Typed confirmation response kinds carried through the resume boundary."""

    OPTION_SELECTION = "OPTION_SELECTION"
    FREE_TEXT = "FREE_TEXT"


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


class ConfirmationResponseV1(TypedDict):
    """Typed confirmation response payload sent through `/runs/{run_id}/resume`."""

    schema_version: Required[Literal[1]]
    response_kind: Literal["OPTION_SELECTION", "FREE_TEXT"]
    selected_option_ids: list[str]
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


class LlmProviderResult(TypedDict):
    """LLM provider result metadata from `docs/07-tool-mcp-internal-interface.md` section 18."""

    structured_output: dict[str, object]
    provider: str
    model: str
    actual_runtime: str
    input_tokens: int
    output_tokens: int
    latency_ms: int
    fallback_reason: NotRequired[str]


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
        "request_understanding.classify",
        "acquisition.plan_sources",
        "context.assess_sufficiency",
        "analysis.analyze",
        "planning.answer_only",
        "planning.draft_plan",
        "review.inspect",
    }
)
CONFIRMATION_RESUME_KIND = "CONFIRMATION"


MULTI_AGENT_GRAPH_STATE_FIELDS = frozenset(MultiAgentGraphState.__annotations__)
PROMPT_SELECTION_KEY_FIELDS = frozenset(PromptSelectionKey.__annotations__)
PROMPT_REF_FIELDS = frozenset(PromptRef.__annotations__)
LLM_PROVIDER_RESULT_FIELDS = frozenset(LlmProviderResult.__annotations__)
LLM_PROVIDER_RESULT_REQUIRED_FIELDS = frozenset(LlmProviderResult.__required_keys__)
LLM_PROVIDER_RESULT_OPTIONAL_FIELDS = frozenset(LlmProviderResult.__optional_keys__)


def build_default_run_budget() -> RunBudgetV1:
    return {
        "schema_version": 1,
        "profile": BudgetProfile.NORMAL.value,
        "llm_calls_used": 0,
        "additional_acquisitions_used": 0,
        "planning_revisions_used": 0,
        "last_rechecked_planning_revision": 0,
        "semantic_revision_signatures_used": [],
    }


def build_semantic_failure_signature_v1(
    *,
    node_id: str,
    failure_reason_codes: list[str],
) -> SemanticFailureSignatureV1:
    return validate_semantic_failure_signature_v1(
        {
            "schema_version": 1,
            "node_id": node_id,
            "failure_reason_codes": failure_reason_codes,
        }
    )


def validate_semantic_failure_signature_v1(value: object) -> SemanticFailureSignatureV1:
    context = "semantic failure signature"
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    required = {"schema_version", "node_id", "failure_reason_codes"}
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"{context} missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"{context} has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 1:
        raise ValueError(f"{context} schema_version must be 1")
    node_id = _require_non_empty_string(value["node_id"], "node_id", context)
    failure_reason_codes = _canonical_string_list(
        value["failure_reason_codes"],
        "failure_reason_codes",
        context=context,
        allow_empty=False,
        unique=True,
        sort_values=True,
    )
    return {
        "schema_version": 1,
        "node_id": node_id,
        "failure_reason_codes": failure_reason_codes,
    }


def validate_run_budget_v1(value: object) -> RunBudgetV1:
    context = "run budget"
    if not isinstance(value, dict):
        raise ValueError(f"{context} must be an object")
    required = {
        "schema_version",
        "profile",
        "llm_calls_used",
        "additional_acquisitions_used",
        "planning_revisions_used",
        "last_rechecked_planning_revision",
        "semantic_revision_signatures_used",
    }
    actual = set(value)
    missing = required - actual
    extra = actual - required
    if missing:
        raise ValueError(f"{context} missing required fields: {sorted(missing)}")
    if extra:
        raise ValueError(f"{context} has unsupported fields: {sorted(extra)}")
    if value["schema_version"] != 1:
        raise ValueError(f"{context} schema_version must be 1")
    profile = _require_budget_profile(value["profile"])
    llm_calls_used = _require_non_negative_int(value["llm_calls_used"], "llm_calls_used", context)
    additional_acquisitions_used = _require_non_negative_int(
        value["additional_acquisitions_used"],
        "additional_acquisitions_used",
        context,
    )
    planning_revisions_used = _require_non_negative_int(
        value["planning_revisions_used"],
        "planning_revisions_used",
        context,
    )
    last_rechecked_planning_revision = _require_non_negative_int(
        value["last_rechecked_planning_revision"],
        "last_rechecked_planning_revision",
        context,
    )
    if additional_acquisitions_used > MAX_ADDITIONAL_ACQUISITIONS:
        raise ValueError("run budget additional_acquisitions_used exceeds the frozen limit")
    if planning_revisions_used > PLANNING_REVISION_PER_RUN:
        raise ValueError("run budget planning_revisions_used exceeds the frozen limit")
    if last_rechecked_planning_revision > planning_revisions_used:
        raise ValueError(
            "run budget last_rechecked_planning_revision must be less than or equal to "
            "planning_revisions_used"
        )
    signatures_raw = value["semantic_revision_signatures_used"]
    if not isinstance(signatures_raw, list):
        raise ValueError("run budget semantic_revision_signatures_used must be a list")
    signatures: list[SemanticFailureSignatureV1] = []
    seen: set[tuple[str, tuple[str, ...]]] = set()
    for item in signatures_raw:
        signature = validate_semantic_failure_signature_v1(item)
        signature_key = _signature_key(signature)
        if signature_key in seen:
            raise ValueError("run budget semantic_revision_signatures_used contains duplicates")
        seen.add(signature_key)
        signatures.append(signature)
    return {
        "schema_version": 1,
        "profile": cast(
            Literal["NORMAL", "REVISION_HEAVY", "RETRIEVAL_HEAVY"],
            profile.value,
        ),
        "llm_calls_used": llm_calls_used,
        "additional_acquisitions_used": additional_acquisitions_used,
        "planning_revisions_used": planning_revisions_used,
        "last_rechecked_planning_revision": last_rechecked_planning_revision,
        "semantic_revision_signatures_used": signatures,
    }


def promote_budget_profile(
    current_profile: object,
    requested_profile: object,
) -> BudgetProfile:
    current = _require_budget_profile(current_profile)
    requested = _require_budget_profile(requested_profile)
    if _BUDGET_PROFILE_ORDER[requested] > _BUDGET_PROFILE_ORDER[current]:
        return requested
    return current


def check_llm_call_budget(
    run_budget: object,
    *,
    provider_calls_requested: int = 1,
) -> BudgetDecisionV1:
    budget = validate_run_budget_v1(run_budget)
    requested = _require_positive_int(
        provider_calls_requested,
        "provider_calls_requested",
        "llm budget gate",
    )
    prospective_calls = budget["llm_calls_used"] + requested
    if prospective_calls > ABSOLUTE_MAX_LLM_CALLS:
        return _deny_budget(budget, BudgetReasonCode.ABSOLUTE_LLM_LIMIT_EXHAUSTED)
    current_profile = BudgetProfile(budget["profile"])
    if prospective_calls > BUDGET_PROFILE_LIMITS[current_profile]:
        return _deny_budget(budget, BudgetReasonCode.PROFILE_LLM_LIMIT_EXHAUSTED)
    return _allow_budget(budget)


def consume_llm_provider_calls(
    run_budget: object,
    *,
    provider_calls_consumed: int = 1,
) -> RunBudgetV1:
    budget = validate_run_budget_v1(run_budget)
    consumed = _require_positive_int(
        provider_calls_consumed,
        "provider_calls_consumed",
        "llm provider accounting",
    )
    updated = dict(budget)
    updated["llm_calls_used"] = budget["llm_calls_used"] + consumed
    return validate_run_budget_v1(updated)


def approve_additional_acquisition(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v1(run_budget)
    if budget["additional_acquisitions_used"] >= MAX_ADDITIONAL_ACQUISITIONS:
        return _deny_budget(budget, BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["additional_acquisitions_used"] = budget["additional_acquisitions_used"] + 1
    updated["profile"] = promote_budget_profile(
        budget["profile"],
        BudgetProfile.RETRIEVAL_HEAVY,
    ).value
    return _allow_budget(validate_run_budget_v1(updated))


def approve_planning_revision(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v1(run_budget)
    if budget["planning_revisions_used"] >= PLANNING_REVISION_PER_RUN:
        return _deny_budget(budget, BudgetReasonCode.PLANNING_REVISION_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["planning_revisions_used"] = budget["planning_revisions_used"] + 1
    updated["profile"] = promote_budget_profile(
        budget["profile"],
        BudgetProfile.REVISION_HEAVY,
    ).value
    return _allow_budget(validate_run_budget_v1(updated))


def approve_review_recheck(run_budget: object) -> BudgetDecisionV1:
    budget = validate_run_budget_v1(run_budget)
    if (
        budget["planning_revisions_used"] <= 0
        or budget["last_rechecked_planning_revision"] >= budget["planning_revisions_used"]
    ):
        return _deny_budget(budget, BudgetReasonCode.REVIEW_RECHECK_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["last_rechecked_planning_revision"] = budget["planning_revisions_used"]
    return _allow_budget(validate_run_budget_v1(updated))


def approve_semantic_revision(
    run_budget: object,
    *,
    signature: object,
) -> BudgetDecisionV1:
    budget = validate_run_budget_v1(run_budget)
    validated_signature = validate_semantic_failure_signature_v1(signature)
    signature_key = _signature_key(validated_signature)
    existing = {_signature_key(item) for item in budget["semantic_revision_signatures_used"]}
    if signature_key in existing:
        return _deny_budget(budget, BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED)
    updated = dict(budget)
    updated["semantic_revision_signatures_used"] = [
        *budget["semantic_revision_signatures_used"],
        validated_signature,
    ]
    return _allow_budget(validate_run_budget_v1(updated))


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


def validate_confirmation_origin_target(value: object) -> str:
    target = _require_string(value, "origin_target")
    if target not in CONFIRMATION_ORIGIN_TARGETS:
        raise ValueError("confirmation origin_target is invalid")
    return target


def validate_confirmation_response_v1(value: object) -> ConfirmationResponseV1:
    if not isinstance(value, dict):
        raise ValueError("confirmation response must be an object")
    required = {"schema_version", "response_kind", "selected_option_ids", "free_text"}
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
    selected_option_ids = _require_string_list(value["selected_option_ids"], "selected_option_ids")
    free_text = value["free_text"]
    if free_text is not None and not isinstance(free_text, str):
        raise ValueError("confirmation response free_text must be a string or null")
    normalized_free_text = None if free_text is None else free_text.strip()
    if response_kind == ConfirmationResponseKind.OPTION_SELECTION.value:
        if not selected_option_ids:
            raise ValueError("OPTION_SELECTION requires at least one selected_option_ids entry")
        if normalized_free_text:
            raise ValueError("OPTION_SELECTION must not include free_text")
        normalized_free_text = None
    else:
        if selected_option_ids:
            raise ValueError("FREE_TEXT must not include selected_option_ids")
        if not normalized_free_text:
            raise ValueError("FREE_TEXT requires non-empty free_text")
    return {
        "schema_version": 1,
        "response_kind": cast(Literal["OPTION_SELECTION", "FREE_TEXT"], response_kind),
        "selected_option_ids": selected_option_ids,
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


def _allow_budget(run_budget: RunBudgetV1) -> BudgetDecisionV1:
    return {
        "schema_version": 1,
        "decision": BudgetDecision.ALLOW.value,
        "budget_reason_code": None,
        "run_budget": run_budget,
    }


def _deny_budget(run_budget: RunBudgetV1, reason_code: BudgetReasonCode) -> BudgetDecisionV1:
    return {
        "schema_version": 1,
        "decision": BudgetDecision.DENY.value,
        "budget_reason_code": reason_code.value,
        "run_budget": run_budget,
    }


def _signature_key(signature: SemanticFailureSignatureV1) -> tuple[str, tuple[str, ...]]:
    return (signature["node_id"], tuple(signature["failure_reason_codes"]))


def _require_budget_profile(value: object) -> BudgetProfile:
    profile = _require_non_empty_string(value, "profile", "run budget")
    try:
        return BudgetProfile(profile)
    except ValueError as error:
        raise ValueError("run budget profile is invalid") from error


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
    "ABSOLUTE_MAX_LLM_CALLS",
    "AdditionalAcquisitionOriginResult",
    "AdditionalAcquisitionRequestV1",
    "CONFIRMATION_ORIGIN_TARGETS",
    "CONFIRMATION_RESUME_KIND",
    "CONFIRMATION_RESPONSE_ALLOWED_KINDS",
    "AnalysisResult",
    "ApiAcquisitionResult",
    "ApiPlanningResult",
    "BUDGET_PROFILE_LIMITS",
    "BudgetDecision",
    "BudgetDecisionV1",
    "BudgetProfile",
    "BudgetReasonCode",
    "ConfirmationResponseKind",
    "ConfirmationResponseV1",
    "ContextResult",
    "DomainValidationResult",
    "FinalizeIntent",
    "FinalizeIntentV1",
    "LLM_PROVIDER_RESULT_FIELDS",
    "LLM_PROVIDER_RESULT_OPTIONAL_FIELDS",
    "LLM_PROVIDER_RESULT_REQUIRED_FIELDS",
    "LlmProviderResult",
    "MULTI_AGENT_GRAPH_STATE_FIELDS",
    "MultiAgentGraphState",
    "PROMPT_REF_FIELDS",
    "PROMPT_SELECTION_KEY_FIELDS",
    "PLANNING_REVISION_PER_RUN",
    "PlanningResult",
    "PromptRef",
    "PromptSelectionKey",
    "RETRIEVAL_HEAVY_MAX_LLM_CALLS",
    "REVIEW_RECHECK_PER_PLANNING_REVISION",
    "REVISION_HEAVY_MAX_LLM_CALLS",
    "RequestUnderstandingResult",
    "ReviewResult",
    "RunBudgetV1",
    "SCHEMA_REPAIR_PER_NODE_CALL",
    "SEMANTIC_REVISION_SAME_FAILURE",
    "SemanticFailureSignatureV1",
    "MAX_ADDITIONAL_ACQUISITIONS",
    "NORMAL_MAX_LLM_CALLS",
    "approve_additional_acquisition",
    "approve_planning_revision",
    "approve_review_recheck",
    "approve_semantic_revision",
    "build_default_run_budget",
    "build_semantic_failure_signature_v1",
    "check_llm_call_budget",
    "consume_llm_provider_calls",
    "promote_budget_profile",
    "validate_run_budget_v1",
    "validate_semantic_failure_signature_v1",
    "validate_confirmation_origin_target",
    "validate_confirmation_response_v1",
    "validate_finalize_intent_v1",
    "validate_additional_acquisition_request_v1",
    "WorkflowPhase",
]
