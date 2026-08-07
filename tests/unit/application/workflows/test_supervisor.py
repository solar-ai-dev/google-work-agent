import json

from google_work_agent.application import derive_finalize_intent
from google_work_agent.application.workflows import (
    BudgetProfile,
    BudgetReasonCode,
    DomainValidationResult,
    FinalizeIntent,
    MultiAgentGraphState,
    SupervisorTarget,
    WorkflowPhase,
    build_default_run_budget,
    route_supervisor,
    validate_user_interrupt_v1,
)


def test_request_complete_routes_to_source_planning() -> None:
    state = _state()

    decision = route_supervisor(
        phase=WorkflowPhase.REQUEST_ANALYSIS,
        state=state,
        result={
            "schema_version": 1,
            "result": "COMPLETE",
            "request_intent": _request_intent(),
            "clarification": None,
            "failure": None,
            "validator_codes": ["OK"],
            "llm_provider_result": {},
        },
    )

    assert decision["target"] == SupervisorTarget.SOURCE_PLANNING.value
    assert decision["next_phase"] == WorkflowPhase.SOURCE_PLANNING.value
    assert decision["state_update"]["request_intent"] == _request_intent()
    assert decision["state_update"]["user_interrupt"] is None
    assert decision["state_update"]["finalize_intent"] is None


def test_source_planning_needs_confirmation_routes_to_waiting_confirmation() -> None:
    state = _state(request_intent=_request_intent(), workflow_phase=WorkflowPhase.SOURCE_PLANNING)

    decision = route_supervisor(
        phase=WorkflowPhase.SOURCE_PLANNING,
        state=state,
        result={
            "schema_version": 1,
            "result": "NEEDS_CONFIRMATION",
            "source_fetch_plans": [],
            "clarification": {
                "schema_version": 1,
                "question": "Which mailbox should we search?",
                "reason_code": "QUERY_SCOPE_EXPANSION_REQUIRES_CONFIRMATION",
                "affected_field_paths": ["semantic_constraints.sources"],
                "options": [{"option_id": "gmail", "label": "Gmail"}],
            },
            "failure": None,
            "validator_codes": ["SOURCE_PLAN_NEEDS_CONFIRMATION"],
            "llm_provider_result": {},
        },
    )

    user_interrupt = validate_user_interrupt_v1(decision["state_update"]["user_interrupt"])

    assert decision["target"] == SupervisorTarget.WAITING_CONFIRMATION.value
    assert decision["next_phase"] == WorkflowPhase.WAITING_CONFIRMATION.value
    assert user_interrupt["origin_target"] == "acquisition.plan_sources"
    assert user_interrupt["options"][0]["option_id"] == "gmail"


def test_source_planning_no_fetch_needed_skips_acquisition_and_builds_canonical_result() -> None:
    state = _state(request_intent=_request_intent(), workflow_phase=WorkflowPhase.SOURCE_PLANNING)

    decision = route_supervisor(
        phase=WorkflowPhase.SOURCE_PLANNING,
        state=state,
        result={
            "schema_version": 1,
            "result": "NO_FETCH_NEEDED",
            "source_fetch_plans": [],
            "clarification": None,
            "failure": None,
            "validator_codes": ["NO_FETCH_NEEDED"],
            "llm_provider_result": {},
        },
    )

    assert decision["target"] == SupervisorTarget.CONTEXT_RETRIEVAL.value
    assert decision["next_phase"] == WorkflowPhase.CONTEXT_RETRIEVAL.value
    assert decision["state_update"]["source_fetch_plans"] == []
    assert decision["state_update"]["acquisition_result"]["status"] == "COMPLETE"
    assert decision["state_update"]["acquisition_result"]["source_summaries"] == []


def test_acquisition_complete_routes_to_context_retrieval() -> None:
    state = _state(workflow_phase=WorkflowPhase.API_ACQUISITION)

    decision = route_supervisor(
        phase=WorkflowPhase.API_ACQUISITION,
        state=state,
        result=_acquisition_result("COMPLETE"),
    )

    assert decision["target"] == SupervisorTarget.CONTEXT_RETRIEVAL.value
    assert decision["next_phase"] == WorkflowPhase.CONTEXT_RETRIEVAL.value
    assert decision["state_update"]["acquisition_result"]["status"] == "COMPLETE"


def test_acquisition_auth_required_routes_to_reauth_boundary() -> None:
    state = _state(workflow_phase=WorkflowPhase.API_ACQUISITION)

    decision = route_supervisor(
        phase=WorkflowPhase.API_ACQUISITION,
        state=state,
        result=_acquisition_result("AUTH_REQUIRED"),
    )

    assert decision["target"] == SupervisorTarget.REAUTH.value
    assert decision["next_phase"] is None
    assert decision["state_update"]["finalize_intent"] is None
    assert decision["state_update"]["acquisition_result"]["status"] == "AUTH_REQUIRED"


def test_context_needs_more_data_routes_to_source_planning_with_budget_update() -> None:
    state = _state(
        request_intent=_request_intent(),
        workflow_phase=WorkflowPhase.CONTEXT_EVALUATION,
    )
    result = _context_result("NEEDS_MORE_DATA")

    decision = route_supervisor(
        phase=WorkflowPhase.CONTEXT_EVALUATION,
        state=state,
        result=result,
    )

    assert decision["target"] == SupervisorTarget.SOURCE_PLANNING.value
    assert decision["next_phase"] == WorkflowPhase.SOURCE_PLANNING.value
    assert decision["budget_decision"]["decision"] == "ALLOW"
    assert decision["state_update"]["retry_budget"]["additional_acquisitions_used"] == 1
    assert (
        decision["state_update"]["retry_budget"]["profile"] == BudgetProfile.RETRIEVAL_HEAVY.value
    )
    assert decision["state_update"]["context_result"] == result


def test_context_needs_confirmation_becomes_user_interrupt() -> None:
    state = _state(
        request_intent=_request_intent(),
        workflow_phase=WorkflowPhase.CONTEXT_EVALUATION,
    )

    decision = route_supervisor(
        phase=WorkflowPhase.CONTEXT_EVALUATION,
        state=state,
        result=_context_result("NEEDS_CONFIRMATION"),
    )

    assert decision["target"] == SupervisorTarget.WAITING_CONFIRMATION.value
    assert decision["next_phase"] == WorkflowPhase.WAITING_CONFIRMATION.value
    user_interrupt = validate_user_interrupt_v1(decision["state_update"]["user_interrupt"])

    assert user_interrupt["origin_target"] == "context.assess_sufficiency"
    assert user_interrupt["resume_kind"] == "CONFIRMATION"
    assert decision["state_update"]["finalize_intent"] is None


def test_analysis_complete_routes_to_solution_planning() -> None:
    state = _state(workflow_phase=WorkflowPhase.WORK_ANALYSIS)

    decision = route_supervisor(
        phase=WorkflowPhase.WORK_ANALYSIS,
        state=state,
        result=_analysis_result("COMPLETE"),
    )

    assert decision["target"] == SupervisorTarget.SOLUTION_PLANNING.value
    assert decision["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert decision["state_update"]["analysis_result"]["status"] == "COMPLETE"


def test_solution_planning_answer_only_routes_to_review_inspect() -> None:
    state = _state(workflow_phase=WorkflowPhase.SOLUTION_PLANNING)
    result = _answer_draft("ANSWER_ONLY")

    decision = route_supervisor(
        phase=WorkflowPhase.SOLUTION_PLANNING,
        state=state,
        result=result,
    )

    assert decision["target"] == SupervisorTarget.PLAN_REVIEW_INSPECT.value
    assert decision["next_phase"] == WorkflowPhase.PLAN_REVIEW.value
    assert decision["state_update"]["answer_draft"] == result
    assert decision["state_update"]["plan_draft"] is None


def test_review_pass_with_plan_routes_to_domain_validation() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        plan_draft=_plan_draft("PLAN_READY"),
    )
    result = _review_result("PASS")

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=result,
    )

    assert decision["target"] == SupervisorTarget.DOMAIN_VALIDATION.value
    assert decision["next_phase"] == WorkflowPhase.DOMAIN_VALIDATION.value
    assert decision["state_update"]["plan_review"] == result


def test_domain_validation_allow_read_skips_approval_and_routes_to_preflight() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.DOMAIN_VALIDATION,
        plan_draft=_plan_draft("PLAN_READY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.DOMAIN_VALIDATION,
        state=state,
        result={
            "schema_version": 1,
            "result": DomainValidationResult.ALLOW_READ.value,
            "reason_codes": ["READ_ONLY_PLAN"],
            "blocked_action_ids": [],
        },
    )

    assert decision["target"] == SupervisorTarget.PREFLIGHT.value
    assert decision["next_phase"] == WorkflowPhase.PREFLIGHT.value
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.PREFLIGHT.value
    assert decision["state_update"]["finalize_intent"] is None


def test_domain_validation_require_approval_routes_to_waiting_approval() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.DOMAIN_VALIDATION,
        plan_draft=_plan_draft("PLAN_READY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.DOMAIN_VALIDATION,
        state=state,
        result={
            "schema_version": 1,
            "result": DomainValidationResult.REQUIRE_APPROVAL.value,
            "reason_codes": ["WRITE_EFFECT_PRESENT"],
            "blocked_action_ids": [],
        },
    )

    assert decision["target"] == SupervisorTarget.WAITING_APPROVAL.value
    assert decision["next_phase"] == WorkflowPhase.WAITING_APPROVAL.value
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.WAITING_APPROVAL.value
    assert decision["state_update"]["finalize_intent"] is None


def test_domain_validation_block_finalizes_with_blocked_intent() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.DOMAIN_VALIDATION,
        plan_draft=_plan_draft("PLAN_READY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.DOMAIN_VALIDATION,
        state=state,
        result={
            "schema_version": 1,
            "result": DomainValidationResult.BLOCK.value,
            "reason_codes": ["FORBIDDEN_DELETE"],
            "blocked_action_ids": ["action-blocked"],
        },
    )

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["reason_code"] == "FORBIDDEN_DELETE"
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.FINALIZE.value
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value


def test_review_pass_with_answer_creates_checkpoint_safe_finalize_intent() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )
    result = _review_result("PASS")

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=result,
    )
    next_state = _apply_state_update(state, decision["state_update"])

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.COMPLETED.value
    assert (
        derive_finalize_intent(state=_checkpoint_roundtrip(next_state))["intent"]
        == FinalizeIntent.COMPLETED.value
    )


def test_review_revise_routes_answer_draft_to_revise_answer_with_shared_budget() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )

    assert decision["target"] == SupervisorTarget.PLANNING_REVISE_ANSWER.value
    assert decision["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert decision["budget_decision"]["decision"] == "ALLOW"
    assert decision["state_update"]["retry_budget"]["planning_revisions_used"] == 1


def test_review_revise_routes_plan_draft_to_revise_plan() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        plan_draft=_plan_draft("PLAN_READY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )

    assert decision["target"] == SupervisorTarget.PLANNING_REVISE_PLAN.value
    assert decision["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert decision["state_update"]["retry_budget"]["planning_revisions_used"] == 1


def test_revised_answer_routes_to_single_review_recheck() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.SOLUTION_PLANNING,
        plan_review=_review_result("REVISE"),
        retry_budget={
            **build_default_run_budget(),
            "planning_revisions_used": 1,
        },
    )

    decision = route_supervisor(
        phase=WorkflowPhase.SOLUTION_PLANNING,
        state=state,
        result=_answer_draft("ANSWER_ONLY"),
    )

    assert decision["target"] == SupervisorTarget.PLAN_REVIEW_RECHECK.value
    assert decision["next_phase"] == WorkflowPhase.PLAN_REVIEW.value
    assert decision["state_update"]["retry_budget"]["last_rechecked_planning_revision"] == 1


def test_review_retrieve_more_budget_deny_blocks_instead_of_guessing_failure() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
        retry_budget={
            **build_default_run_budget(),
            "additional_acquisitions_used": 2,
            "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
        },
    )
    result = _review_result("RETRIEVE_MORE")

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=result,
    )

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["budget_decision"]["decision"] == "DENY"
    assert (
        decision["budget_decision"]["budget_reason_code"]
        == BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED.value
    )
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value


def test_additional_acquisition_budget_deny_preserves_partial_result_kind_when_present() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
        acquisition_result=_acquisition_result("PARTIAL"),
        retry_budget={
            **build_default_run_budget(),
            "additional_acquisitions_used": 2,
            "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
        },
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("RETRIEVE_MORE"),
    )

    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value
    assert decision["state_update"]["finalize_intent"]["result_kind"] == "PARTIAL"


def test_request_invalid_routes_to_blocked_finalize() -> None:
    state = _state(workflow_phase=WorkflowPhase.REQUEST_ANALYSIS)

    decision = route_supervisor(
        phase=WorkflowPhase.REQUEST_ANALYSIS,
        state=state,
        result={
            "schema_version": 1,
            "result": "INVALID",
            "request_intent": _request_intent(),
            "clarification": None,
            "failure": {
                "schema_version": 1,
                "reason_code": "UNSUPPORTED_SCOPE",
                "user_safe_message": "not supported",
                "diagnostic": "unsupported",
            },
            "validator_codes": ["UNSUPPORTED_SCOPE"],
            "llm_provider_result": {},
        },
    )

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value
    assert decision["reason_code"] == "UNSUPPORTED_SCOPE"


def test_recovery_phase_routes_to_recovery_boundary() -> None:
    state = _state(workflow_phase=WorkflowPhase.RECOVERY)

    decision = route_supervisor(
        phase=WorkflowPhase.RECOVERY,
        state=state,
        result=None,
    )

    assert decision["target"] == SupervisorTarget.RECOVERY.value
    assert decision["next_phase"] == WorkflowPhase.RECOVERY.value


def _state(
    *,
    workflow_phase: WorkflowPhase = WorkflowPhase.REQUEST_ANALYSIS,
    request_intent: dict[str, object] | None = None,
    acquisition_result: dict[str, object] | None = None,
    context_result: dict[str, object] | None = None,
    analysis_result: dict[str, object] | None = None,
    answer_draft: dict[str, object] | None = None,
    plan_draft: dict[str, object] | None = None,
    plan_review: dict[str, object] | None = None,
    retry_budget: dict[str, object] | None = None,
) -> MultiAgentGraphState:
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "conversation_id": "conv-1",
        "thread_id": "thread-1",
        "workflow_phase": workflow_phase.value,
        "request_intent": request_intent,
        "source_fetch_plans": [],
        "acquisition_result": acquisition_result,
        "context_result": context_result,
        "analysis_result": analysis_result,
        "answer_draft": answer_draft,
        "plan_draft": plan_draft,
        "plan_review": plan_review,
        "approved_plan_id": None,
        "execution_summary": None,
        "verification_summary": None,
        "finalize_intent": None,
        "user_interrupt": None,
        "retry_budget": retry_budget or build_default_run_budget(),
        "prompt_context": {},
        "trace_context": {},
    }


def _request_intent() -> dict[str, object]:
    return {
        "schema_version": 1,
        "goal": {
            "summary": "Summarize the latest status.",
            "user_visible_objective": "Summarize the latest status.",
        },
        "completion_criteria": ["Provide the latest status."],
        "semantic_constraints": {
            "topics": [],
            "people": [],
            "time": [],
            "sources": [],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {
            "is_ambiguous": False,
            "items": [],
        },
        "unsupported_scope": {
            "is_unsupported": False,
            "reason_code": None,
            "explanation": None,
        },
    }


def _acquisition_result(status: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "resource_handles": [],
        "source_summaries": [],
        "missing_slots": [],
        "remaining_budget": {
            "sources": 0,
            "pages": 0,
            "candidates": 0,
            "details": 0,
        },
    }


def _context_result(status: str) -> dict[str, object]:
    additional_request = None
    ambiguity = None
    if status == "NEEDS_MORE_DATA":
        additional_request = {
            "schema_version": 1,
            "origin_phase": WorkflowPhase.CONTEXT_EVALUATION.value,
            "origin_result": "NEEDS_MORE_DATA",
            "missing_slots": ["missing-date"],
            "missing_information": ["Need the missing date."],
            "evidence_refs": ["evidence-1"],
            "reason_codes": ["EVIDENCE_GAP"],
        }
    if status == "NEEDS_CONFIRMATION":
        ambiguity = {
            "question": "Which date should be prioritized?",
            "reason_code": "MULTIPLE_DATES",
            "affected_field_paths": ["semantic_constraints.time"],
            "options": [],
        }
    return {
        "schema_version": 1,
        "status": status,
        "context_bundle": {
            "schema_version": 1,
            "resource_refs": [{"resource_handle": "message:1"}],
            "segment_refs": [{"segment_id": "seg-1"}],
            "evidence_refs": ["evidence-1"],
            "normalized_context": [],
            "missing_information": ["Need the missing date."]
            if status == "NEEDS_MORE_DATA"
            else [],
            "ambiguity": ambiguity,
        },
        "evidence_drafts": [
            {
                "schema_version": 1,
                "evidence_id": "evidence-1",
                "resource_handle": "message:1",
                "segment_id": "seg-1",
                "kind": "FACT",
                "excerpt": "Latest update",
                "locator": None,
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "selected_segment_ids": ["seg-1"],
        "excluded_resource_handles": [],
        "missing_slots": ["missing-date"] if status == "NEEDS_MORE_DATA" else [],
        "additional_acquisition_request": additional_request,
        "sufficiency": {},
        "llm_provider_result": {},
    }


def _analysis_result(status: str) -> dict[str, object]:
    additional_request = None
    confirmation = None
    if status == "NEEDS_MORE_DATA":
        additional_request = {
            "schema_version": 1,
            "origin_phase": WorkflowPhase.WORK_ANALYSIS.value,
            "origin_result": "NEEDS_MORE_DATA",
            "missing_slots": [],
            "missing_information": ["Need the due date."],
            "evidence_refs": ["evidence-1"],
            "reason_codes": ["EVIDENCE_GAP"],
        }
    if status == "NEEDS_CONFIRMATION":
        confirmation = {
            "question": "Should we focus on only this week?",
            "reason_code": "TIME_SCOPE_CONFIRMATION",
            "affected_field_paths": ["semantic_constraints.time"],
            "options": [],
        }
    return {
        "schema_version": 1,
        "status": status,
        "summary": "Analysis summary",
        "findings": [
            {
                "schema_version": 1,
                "finding_id": "finding-1",
                "kind": "FACT",
                "statement": "A fact",
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["message:1"],
                "segment_refs": ["seg-1"],
                "related_resource_handles": ["message:1"],
                "reason_codes": ["EVIDENCE_SUPPORTED"],
            }
        ],
        "missing_information": ["Need the due date."] if status == "NEEDS_MORE_DATA" else [],
        "confirmation": confirmation,
        "blockers": ["unsupported"] if status == "BLOCKED" else [],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [{"resource_handle": "message:1"}],
        "segment_refs": [{"segment_id": "seg-1"}],
        "additional_acquisition_request": additional_request,
        "llm_provider_result": {},
    }


def _answer_draft(status: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "answer": "Here is the answer.",
        "evidence_refs": ["evidence-1"],
        "resource_refs": [{"resource_handle": "message:1"}],
        "reason_codes": ["ANSWER_SUPPORTED"] if status == "ANSWER_ONLY" else ["PLANNING_BLOCKED"],
        "confirmation": (
            None
            if status != "NEEDS_CONFIRMATION"
            else {
                "question": "Should we include the tentative item?",
                "reason_code": "ANSWER_SCOPE_CONFIRMATION",
                "affected_field_paths": ["answer"],
                "options": [],
            }
        ),
        "blockers": [] if status != "BLOCKED" else ["unsupported"],
    }


def _plan_draft(status: str) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": status,
        "plan_id": "plan-1",
        "summary": "Plan summary",
        "objective": "Plan objective",
        "actions": [] if status != "PLAN_READY" else [_action_draft()],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [{"resource_handle": "message:1"}],
        "confirmation": (
            None
            if status != "NEEDS_CONFIRMATION"
            else {
                "question": "Should this action be approved?",
                "reason_code": "PLAN_SCOPE_CONFIRMATION",
                "affected_field_paths": ["actions[0]"],
                "options": [],
            }
        ),
    }


def _action_draft() -> dict[str, object]:
    return {
        "schema_version": 1,
        "action_id": "action-1",
        "position": 1,
        "effect": "READ",
        "tool_name": "gmail.read_thread",
        "arguments": {},
        "expected": {},
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["message:1"],
        "target_resource_ref_id": None,
        "depends_on_action_ids": [],
        "user_visible_reason": "Need the latest thread.",
    }


def _review_result(status: str) -> dict[str, object]:
    request = None
    confirmation = None
    issues = []
    blockers = []
    if status == "REVISE":
        issues = [
            {
                "schema_version": 1,
                "issue_id": "issue-1",
                "kind": "MISSING_POINT",
                "message": "Missing one point",
                "affected_action_ids": [],
                "affected_field_paths": ["answer"],
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["message:1"],
                "reason_codes": ["PLAN_REQUIRED_ACTION_MISSING"],
            }
        ]
    if status == "RETRIEVE_MORE":
        issues = [
            {
                "schema_version": 1,
                "issue_id": "issue-1",
                "kind": "EVIDENCE_GAP",
                "message": "Need more evidence",
                "affected_action_ids": [],
                "affected_field_paths": ["answer"],
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["message:1"],
                "reason_codes": ["EVIDENCE_GAP"],
            }
        ]
        request = {
            "schema_version": 1,
            "origin_phase": WorkflowPhase.PLAN_REVIEW.value,
            "origin_result": "RETRIEVE_MORE",
            "missing_slots": [],
            "missing_information": ["Need one more source."],
            "evidence_refs": ["evidence-1"],
            "reason_codes": ["EVIDENCE_GAP"],
        }
    if status == "CONFIRM":
        confirmation = {
            "question": "Which interpretation is correct?",
            "reason_code": "REVIEW_CONFIRMATION_REQUIRED",
            "affected_field_paths": ["answer"],
            "options": [],
        }
    if status == "BLOCK":
        blockers = ["policy blocker"]
    return {
        "schema_version": 1,
        "status": status,
        "summary": "Review summary",
        "issues": issues,
        "confirmation": confirmation,
        "blockers": blockers,
        "additional_acquisition_request": request,
        "llm_provider_result": {},
    }


def _apply_state_update(
    state: MultiAgentGraphState,
    state_update: dict[str, object],
) -> MultiAgentGraphState:
    updated = dict(state)
    updated.update(state_update)
    return updated  # type: ignore[return-value]


def _checkpoint_roundtrip(state: MultiAgentGraphState) -> MultiAgentGraphState:
    return json.loads(json.dumps(state))  # type: ignore[return-value]
