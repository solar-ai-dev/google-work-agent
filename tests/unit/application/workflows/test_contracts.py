from enum import StrEnum

from google_work_agent.application.workflows import (
    LLM_PROVIDER_RESULT_FIELDS,
    LLM_PROVIDER_RESULT_OPTIONAL_FIELDS,
    LLM_PROVIDER_RESULT_REQUIRED_FIELDS,
    MULTI_AGENT_GRAPH_STATE_FIELDS,
    PROMPT_REF_FIELDS,
    PROMPT_SELECTION_KEY_FIELDS,
    AnalysisResult,
    ApiAcquisitionResult,
    ApiPlanningResult,
    ContextResult,
    DomainValidationResult,
    PlanningResult,
    RequestUnderstandingResult,
    ReviewResult,
    WorkflowPhase,
)


def _values(enum_type: type[StrEnum]) -> tuple[str, ...]:
    return tuple(item.value for item in enum_type)


def test_multi_agent_graph_state_fields_match_workflow_document() -> None:
    assert {
        "schema_version",
        "run_id",
        "conversation_id",
        "thread_id",
        "workflow_phase",
        "request_intent",
        "source_fetch_plans",
        "acquisition_result",
        "context_result",
        "analysis_result",
        "plan_draft",
        "plan_review",
        "approved_plan_id",
        "execution_summary",
        "verification_summary",
        "user_interrupt",
        "retry_budget",
        "prompt_context",
        "trace_context",
    } == MULTI_AGENT_GRAPH_STATE_FIELDS


def test_multi_agent_graph_state_has_no_implementation_only_fields() -> None:
    assert "run_version" not in MULTI_AGENT_GRAPH_STATE_FIELDS
    assert "pending_command_id" not in MULTI_AGENT_GRAPH_STATE_FIELDS
    assert "answer_output" not in MULTI_AGENT_GRAPH_STATE_FIELDS
    assert "command_result" not in MULTI_AGENT_GRAPH_STATE_FIELDS
    assert "error" not in MULTI_AGENT_GRAPH_STATE_FIELDS


def test_workflow_phase_values_match_workflow_document() -> None:
    assert _values(WorkflowPhase) == (
        "INITIALIZE",
        "REQUEST_ANALYSIS",
        "WAITING_CONFIRMATION",
        "SOURCE_PLANNING",
        "API_ACQUISITION",
        "CONTEXT_RETRIEVAL",
        "CONTEXT_EVALUATION",
        "WORK_ANALYSIS",
        "SOLUTION_PLANNING",
        "PLAN_REVIEW",
        "DOMAIN_VALIDATION",
        "WAITING_APPROVAL",
        "PREFLIGHT",
        "ACTION_EXECUTION",
        "VERIFICATION",
        "RESPONSE_SYNTHESIS",
        "RECOVERY",
        "FINALIZE",
    )


def test_request_understanding_result_values_match_workflow_document() -> None:
    assert _values(RequestUnderstandingResult) == (
        "COMPLETE",
        "NEEDS_CONFIRMATION",
        "INVALID",
    )


def test_api_planning_result_values_match_workflow_document() -> None:
    assert _values(ApiPlanningResult) == (
        "PLAN_READY",
        "NO_FETCH_NEEDED",
        "NEEDS_CONFIRMATION",
        "BLOCKED",
    )


def test_api_acquisition_result_values_match_workflow_document() -> None:
    assert _values(ApiAcquisitionResult) == (
        "COMPLETE",
        "PARTIAL",
        "AUTH_REQUIRED",
        "RATE_LIMITED",
        "BUDGET_EXHAUSTED",
        "FAILED",
    )


def test_context_result_values_match_workflow_document() -> None:
    assert _values(ContextResult) == (
        "SUFFICIENT",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "PARTIAL",
        "BLOCKED",
    )


def test_analysis_result_values_match_workflow_document() -> None:
    assert _values(AnalysisResult) == (
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "BLOCKED",
    )


def test_planning_result_values_match_workflow_document() -> None:
    assert _values(PlanningResult) == (
        "ANSWER_ONLY",
        "PLAN_READY",
        "NEEDS_CONFIRMATION",
        "BLOCKED",
    )


def test_review_result_values_match_workflow_document() -> None:
    assert _values(ReviewResult) == (
        "PASS",
        "REVISE",
        "RETRIEVE_MORE",
        "CONFIRM",
        "BLOCK",
    )


def test_domain_validation_result_values_match_workflow_document() -> None:
    assert _values(DomainValidationResult) == (
        "ALLOW_READ",
        "REQUIRE_APPROVAL",
        "BLOCK",
    )


def test_prompt_selection_key_fields_match_workflow_document() -> None:
    assert {
        "agent_role",
        "subgraph_name",
        "node_name",
        "node_state",
        "purpose",
        "input_schema_version",
        "output_schema_version",
    } == PROMPT_SELECTION_KEY_FIELDS


def test_prompt_ref_fields_match_workflow_document() -> None:
    assert {
        "prompt_bundle_version",
        "prompt_id",
        "prompt_version",
        "content_hash",
        "agent_role",
        "subgraph_name",
        "node_name",
        "node_state",
        "purpose",
        "input_schema_version",
        "output_schema_version",
    } == PROMPT_REF_FIELDS


def test_prompt_ref_has_no_prompt_content_fields() -> None:
    assert "content" not in PROMPT_REF_FIELDS
    assert "prompt_text" not in PROMPT_REF_FIELDS
    assert "template" not in PROMPT_REF_FIELDS
    assert "system_prompt" not in PROMPT_REF_FIELDS
    assert "raw_prompt" not in PROMPT_REF_FIELDS


def test_llm_provider_result_fields_match_interface_document() -> None:
    assert {
        "structured_output",
        "provider",
        "model",
        "actual_runtime",
        "input_tokens",
        "output_tokens",
        "latency_ms",
        "fallback_reason",
    } == LLM_PROVIDER_RESULT_FIELDS


def test_llm_provider_result_only_fallback_reason_is_optional() -> None:
    assert {
        "structured_output",
        "provider",
        "model",
        "actual_runtime",
        "input_tokens",
        "output_tokens",
        "latency_ms",
    } == LLM_PROVIDER_RESULT_REQUIRED_FIELDS
    assert {"fallback_reason"} == LLM_PROVIDER_RESULT_OPTIONAL_FIELDS
