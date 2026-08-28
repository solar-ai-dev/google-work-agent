from enum import StrEnum

import pytest

from google_work_agent.application.orchestration.contracts import (
    ADDITIONAL_ACQUISITION_ALLOWED_PHASES,
    ADDITIONAL_ACQUISITION_ALLOWED_RESULTS,
    AGENT_LOCAL_STATE_FIELDS,
    CONFIRMATION_ORIGIN_TARGETS,
    CONFIRMATION_RESPONSE_ALLOWED_KINDS,
    CONFIRMATION_RESUME_KIND,
    LLM_PROVIDER_RESULT_FIELDS,
    LLM_PROVIDER_RESULT_OPTIONAL_FIELDS,
    LLM_PROVIDER_RESULT_REQUIRED_FIELDS,
    MULTI_AGENT_GRAPH_STATE_FIELDS,
    PROMPT_REF_FIELDS,
    PROMPT_SELECTION_KEY_FIELDS,
    AdditionalAcquisitionOriginResult,
    AnalysisResult,
    ApiAcquisitionResult,
    ApiPlanningResult,
    ConfirmationResponseKind,
    ContextResult,
    DomainValidationOutputV1,
    DomainValidationResult,
    FinalizeIntent,
    PlanningResult,
    RequestUnderstandingResult,
    ReviewResult,
    UserInterruptV1,
    WorkflowPhase,
    validate_additional_acquisition_request_v1,
    validate_confirmation_origin_target,
    validate_confirmation_response_projection_v1,
    validate_domain_validation_output_v1,
    validate_finalize_intent_v1,
    validate_user_interrupt_v1,
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
        "tool_route_plan",
        "workflow_signal",
        "source_fetch_plans",
        "acquisition_result",
        "retrieval_result",
        "context_result",
        "analysis_result",
        "answer_draft",
        "plan_draft",
        "plan_review",
        "approved_plan_id",
        "execution_summary",
        "verification_summary",
        "finalize_intent",
        "user_interrupt",
        "policy_confirmation_receipts",
        "retry_budget",
        "prompt_context",
        "trace_context",
    } == MULTI_AGENT_GRAPH_STATE_FIELDS
    assert len(MULTI_AGENT_GRAPH_STATE_FIELDS) == 25


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
        "TOOL_ROUTING",
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
        "ROUTE_RECONSIDERATION_REQUIRED",
        "PARTIAL",
        "BLOCKED",
    )


def test_analysis_result_values_match_workflow_document() -> None:
    assert _values(AnalysisResult) == (
        "COMPLETE",
        "NEEDS_MORE_DATA",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    )


def test_planning_result_values_match_workflow_document() -> None:
    assert _values(PlanningResult) == (
        "ANSWER_ONLY",
        "PLAN_READY",
        "NEEDS_CONFIRMATION",
        "ROUTE_RECONSIDERATION_REQUIRED",
        "BLOCKED",
    )


def test_review_result_values_match_workflow_document() -> None:
    assert _values(ReviewResult) == (
        "PASS",
        "REVISE",
        "RETRIEVE_MORE",
        "ROUTE_RECONSIDERATION",
        "CONFIRM",
        "BLOCK",
    )


def test_domain_validation_result_values_match_workflow_document() -> None:
    assert _values(DomainValidationResult) == (
        "ALLOW_READ",
        "REQUIRE_APPROVAL",
        "BLOCK",
    )


def test_domain_validation_output_validator_accepts_minimal_runtime_contract() -> None:
    output: DomainValidationOutputV1 = validate_domain_validation_output_v1(
        {
            "schema_version": 1,
            "result": "REQUIRE_APPROVAL",
            "reason_codes": ["WRITE_EFFECT_PRESENT"],
            "blocked_action_ids": [],
        }
    )

    assert output["result"] == "REQUIRE_APPROVAL"
    assert output["blocked_action_ids"] == []


def test_finalize_intent_values_match_terminal_boundary_contract() -> None:
    assert _values(FinalizeIntent) == (
        "COMPLETED",
        "BLOCKED",
        "FAILED",
    )


def test_finalize_intent_validator_accepts_minimal_runtime_contract() -> None:
    finalized = validate_finalize_intent_v1(
        {
            "schema_version": 1,
            "intent": "FAILED",
            "reason_code": "OUTPUT_SCHEMA_INVALID",
            "result_kind": None,
        }
    )

    assert finalized["intent"] == "FAILED"
    assert finalized["reason_code"] == "OUTPUT_SCHEMA_INVALID"


def test_finalize_intent_validator_rejects_non_terminal_values() -> None:
    with pytest.raises(ValueError, match="finalize intent intent is invalid"):
        validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": "REAUTH_REQUIRED",
                "reason_code": "AUTH_REQUIRED",
            }
        )

    with pytest.raises(ValueError, match="finalize intent result_kind must be PARTIAL or null"):
        validate_finalize_intent_v1(
            {
                "schema_version": 1,
                "intent": "COMPLETED",
                "reason_code": "ANSWER_ONLY_REVIEW_PASS",
                "result_kind": "COMPLETED",
            }
        )


def test_additional_acquisition_origin_result_values_match_gap_a_contract() -> None:
    assert _values(AdditionalAcquisitionOriginResult) == (
        "NEEDS_MORE_DATA",
        "RETRIEVE_MORE",
    )
    assert {
        "CONTEXT_EVALUATION",
        "WORK_ANALYSIS",
        "PLAN_REVIEW",
    } == ADDITIONAL_ACQUISITION_ALLOWED_PHASES
    assert {
        "NEEDS_MORE_DATA",
        "RETRIEVE_MORE",
    } == ADDITIONAL_ACQUISITION_ALLOWED_RESULTS


def test_additional_acquisition_request_validator_accepts_minimal_runtime_contract() -> None:
    request = validate_additional_acquisition_request_v1(
        {
            "schema_version": 1,
            "origin_phase": "WORK_ANALYSIS",
            "origin_result": "NEEDS_MORE_DATA",
            "missing_slots": [],
            "missing_information": ["Need the current due date."],
            "evidence_refs": ["evidence-1"],
            "reason_codes": ["EVIDENCE_SUPPORTED"],
        },
        allowed_evidence_refs={"evidence-1"},
    )

    assert request["origin_phase"] == "WORK_ANALYSIS"
    assert request["origin_result"] == "NEEDS_MORE_DATA"


def test_additional_acquisition_request_rejects_empty_handoff_reason() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "additional acquisition request requires at least one of missing_slots, "
            "missing_information, or reason_codes"
        ),
    ):
        validate_additional_acquisition_request_v1(
            {
                "schema_version": 1,
                "origin_phase": "PLAN_REVIEW",
                "origin_result": "RETRIEVE_MORE",
                "missing_slots": [],
                "missing_information": [],
                "evidence_refs": ["evidence-1"],
                "reason_codes": [],
            },
            allowed_evidence_refs={"evidence-1"},
        )


def test_confirmation_contract_constants_match_gap_b_contract() -> None:
    assert _values(ConfirmationResponseKind) == (
        "OPTION",
        "FREE_TEXT",
        "DECLINE",
    )
    assert {"OPTION", "FREE_TEXT", "DECLINE"} == CONFIRMATION_RESPONSE_ALLOWED_KINDS
    assert {
        "request.detect_ambiguity",
        "tool_route.finalize",
        "acquisition.plan_sources",
        "context.assess_sufficiency",
        "analysis.analyze",
        "planning.answer_only",
        "planning.draft_plan",
        "review.inspect",
    } == CONFIRMATION_ORIGIN_TARGETS
    assert CONFIRMATION_RESUME_KIND == "CONFIRMATION"


def test_user_interrupt_validator_preserves_confirmation_projection() -> None:
    user_interrupt: UserInterruptV1 = validate_user_interrupt_v1(
        {
            "schema_version": 1,
            "interrupt_kind": "CONFIRMATION",
            "resume_kind": "CONFIRMATION",
            "origin_target": "review.inspect",
            "question": "Which version should we keep?",
            "affected_field_paths": ["draft.summary"],
            "reason_code": "REVIEW_CONFIRMATION_REQUIRED",
            "known_context_summary": "Review the current draft.",
            "options": [
                {"option_id": "keep-current", "label": "Keep current"},
                {"option_id": "revise", "label": "Revise"},
            ],
        }
    )

    assert user_interrupt["origin_target"] == "review.inspect"
    assert user_interrupt["resume_kind"] == "CONFIRMATION"
    assert [item["option_id"] for item in user_interrupt["options"]] == [
        "keep-current",
        "revise",
    ]


def test_confirmation_origin_target_and_response_validators_enforce_runtime_contract() -> None:
    assert validate_confirmation_origin_target("review.inspect") == "review.inspect"

    selection = validate_confirmation_response_projection_v1(
        {
            "schema_version": 1,
            "response_kind": "OPTION",
            "selected_option": "option-1",
            "free_text": None,
        }
    )
    free_text = validate_confirmation_response_projection_v1(
        {
            "schema_version": 1,
            "response_kind": "FREE_TEXT",
            "selected_option": None,
            "free_text": "Use the existing draft only.",
        }
    )

    assert selection["selected_option"] == "option-1"
    assert free_text["free_text"] == "Use the existing draft only."

    with pytest.raises(ValueError, match="confirmation origin_target is invalid"):
        validate_confirmation_origin_target("planning.revise_plan")

    with pytest.raises(ValueError, match="OPTION requires selected_option"):
        validate_confirmation_response_projection_v1(
            {
                "schema_version": 1,
                "response_kind": "OPTION",
                "selected_option": None,
                "free_text": None,
            }
        )

    with pytest.raises(ValueError, match="FREE_TEXT requires non-empty free_text"):
        validate_confirmation_response_projection_v1(
            {
                "schema_version": 1,
                "response_kind": "FREE_TEXT",
                "selected_option": None,
                "free_text": "   ",
            }
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


def test_agent_local_state_fields_match_native_subgraph_contract() -> None:
    assert {
        "schema_version",
        "agent_role",
        "invocation_id",
        "node_state",
        "input_projection",
        "candidate_output",
        "prompt_ref",
        "attempt_no",
        "schema_repair_count",
        "semantic_revision_count",
        "failure_record",
        "disposition",
        "typed_result",
    } == AGENT_LOCAL_STATE_FIELDS


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
