"""Workflow contracts taken from the agent workflow design document."""

from enum import StrEnum
from typing import Literal, NotRequired, Required, TypedDict, cast


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
    user_interrupt: dict[str, object] | None
    retry_budget: dict[str, object]
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
    "ConfirmationResponseV1",
    "ContextResult",
    "DomainValidationResult",
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
    "validate_confirmation_origin_target",
    "validate_confirmation_response_v1",
    "validate_additional_acquisition_request_v1",
    "WorkflowPhase",
]
