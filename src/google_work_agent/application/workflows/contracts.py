"""Workflow contracts taken from the agent workflow design document."""

from enum import StrEnum
from typing import NotRequired, TypedDict


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


MULTI_AGENT_GRAPH_STATE_FIELDS = frozenset(MultiAgentGraphState.__annotations__)
PROMPT_SELECTION_KEY_FIELDS = frozenset(PromptSelectionKey.__annotations__)
PROMPT_REF_FIELDS = frozenset(PromptRef.__annotations__)
LLM_PROVIDER_RESULT_FIELDS = frozenset(LlmProviderResult.__annotations__)
LLM_PROVIDER_RESULT_REQUIRED_FIELDS = frozenset(LlmProviderResult.__required_keys__)
LLM_PROVIDER_RESULT_OPTIONAL_FIELDS = frozenset(LlmProviderResult.__optional_keys__)

__all__ = [
    "AnalysisResult",
    "ApiAcquisitionResult",
    "ApiPlanningResult",
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
    "WorkflowPhase",
]
