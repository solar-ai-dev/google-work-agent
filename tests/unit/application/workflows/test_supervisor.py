import json
from typing import Literal, cast

import pytest
from tests.support.legacy_write.write_actions import WriteActionResponse

from google_work_agent.application.orchestration.contracts import (
    AdditionalAcquisitionRequestV1,
    BudgetProfile,
    BudgetReasonCode,
    DomainValidationResult,
    FinalizeIntent,
    GraphStateUpdateV1,
    MultiAgentGraphState,
    RunBudgetV1,
    WorkflowPhase,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
    validate_user_interrupt_v1,
)
from google_work_agent.application.orchestration.handoff_contracts import (
    AcquisitionResultV1,
    ActionDraftV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
    ContextRetrievalResultV1,
    PlanReviewResultV1,
    RequestIntentV2,
    ReviewIssueV1,
)
from google_work_agent.application.orchestration.supervisor import (
    SupervisorTarget,
    route_supervisor,
)
from google_work_agent.application.use_cases.action.read_contracts import (
    ReadActionCommandResponse,
)
from google_work_agent.application.use_cases.run.run_terminal import derive_finalize_intent


def test_request_complete_routes_to_tool_route() -> None:
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

    assert decision["target"] == SupervisorTarget.TOOL_ROUTE.value
    assert decision["next_phase"] == WorkflowPhase.TOOL_ROUTING.value
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


def test_tool_route_ready_enters_retrieval_for_initial_query_planning() -> None:
    plan = _tool_route_plan()
    decision = route_supervisor(
        phase=WorkflowPhase.TOOL_ROUTING,
        state=_state(request_intent=_request_intent()),
        result={
            "schema_version": 1,
            "disposition": "ROUTE_READY",
            "tool_route_plan": plan,
            "workflow_signal": None,
            "reason_codes": [],
        },
    )

    assert decision["target"] == SupervisorTarget.CONTEXT_RETRIEVAL.value
    assert decision["next_phase"] == WorkflowPhase.CONTEXT_RETRIEVAL.value
    assert decision["state_update"]["tool_route_plan"] == plan


def test_unknown_tool_route_disposition_fails_closed_to_recovery() -> None:
    decision = route_supervisor(
        phase=WorkflowPhase.TOOL_ROUTING,
        state=_state(request_intent=_request_intent()),
        result={
            "schema_version": 1,
            "disposition": "UNKNOWN",
            "tool_route_plan": None,
            "workflow_signal": None,
            "reason_codes": [],
        },
    )

    assert decision["target"] == SupervisorTarget.RECOVERY.value
    assert decision["reason_code"] == "TOOL_ROUTE_CONTRACT_VIOLATION"


def test_downstream_route_reconsideration_returns_to_tool_route_owner() -> None:
    decision = route_supervisor(
        phase=WorkflowPhase.SOLUTION_PLANNING,
        state=_state(request_intent=_request_intent()),
        result={
            "schema_version": 2,
            "status": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": ["NEW_RESOURCE_ROUTE_REQUIRED"],
        },
    )

    assert decision["target"] == SupervisorTarget.TOOL_ROUTE.value
    assert decision["state_update"]["workflow_signal"] == {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": ["NEW_RESOURCE_ROUTE_REQUIRED"],
    }


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
    assert decision["state_update"]["acquisition_result"] is not None
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
    assert decision["state_update"]["acquisition_result"] is not None
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
    assert decision["state_update"]["acquisition_result"] is not None
    assert decision["state_update"]["acquisition_result"]["status"] == "AUTH_REQUIRED"


def test_context_needs_more_data_routes_to_source_planning_with_budget_update() -> None:
    state = _state(
        request_intent=_request_intent(),
        workflow_phase=WorkflowPhase.CONTEXT_EVALUATION,
    )
    with pytest.raises(ValueError, match="bounded local loop"):
        route_supervisor(
            phase=WorkflowPhase.CONTEXT_EVALUATION,
            state=state,
            result={"disposition": "NEEDS_MORE_DATA", "typed_result": None},
        )


def test_context_needs_confirmation_becomes_user_interrupt() -> None:
    state = _state(
        request_intent=_request_intent(),
        workflow_phase=WorkflowPhase.CONTEXT_EVALUATION,
    )
    with pytest.raises(ValueError, match="owner checkpoint"):
        route_supervisor(
            phase=WorkflowPhase.CONTEXT_EVALUATION,
            state=state,
            result={"disposition": "NEEDS_CONFIRMATION", "typed_result": None},
        )


def test_work_analysis_routing_is_owned_by_canonical_subgraph() -> None:
    state = _state(workflow_phase=WorkflowPhase.WORK_ANALYSIS)

    with pytest.raises(ValueError, match="canonical eight-node subgraph"):
        route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=state,
            result={},
        )


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
    assert decision["state_update"]["finalize_intent"] is not None
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value


def test_preflight_read_claim_routes_to_action_execution() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        plan_draft=_plan_draft("PLAN_READY"),
        approved_plan_id="approved-plan-1",
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PREFLIGHT,
        state=state,
        result=ReadActionCommandResponse(
            applied=True,
            result_code="TRANSITION_APPLIED",
            action_id="action-read-1",
            action_status="EXECUTING",
            action_version=3,
            next_allowed_commands=("complete_read_action",),
            plan_completed=False,
            run_completed=False,
            partial=False,
            safe_error_code=None,
            conflict_detail=None,
        ),
    )

    assert decision["target"] == SupervisorTarget.ACTION_EXECUTION.value
    assert decision["next_phase"] == WorkflowPhase.ACTION_EXECUTION.value
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.ACTION_EXECUTION.value
    assert decision["state_update"]["finalize_intent"] is None


def test_preflight_write_claim_routes_to_action_execution() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        plan_draft=_plan_draft("PLAN_READY"),
        approved_plan_id="approved-plan-1",
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PREFLIGHT,
        state=state,
        result=WriteActionResponse(
            applied=True,
            result_code="TRANSITION_APPLIED",
            action_id="action-write-1",
            action_status="EXECUTING",
            action_version=5,
            next_allowed_commands=("store_execution_success",),
            approval_id="approval-1",
            attempt_id="attempt-1",
            claim_token="claim-token-1",
            safe_error_code=None,
            conflict_detail=None,
        ),
    )

    assert decision["target"] == SupervisorTarget.ACTION_EXECUTION.value
    assert decision["next_phase"] == WorkflowPhase.ACTION_EXECUTION.value
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.ACTION_EXECUTION.value
    assert decision["state_update"]["finalize_intent"] is None


def test_preflight_reauth_required_routes_to_reauth_boundary() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        plan_draft=_plan_draft("PLAN_READY"),
        approved_plan_id="approved-plan-1",
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PREFLIGHT,
        state=state,
        result={
            "applied": False,
            "result_code": "STATE_CONFLICT",
            "action_id": "action-write-1",
            "action_status": "APPROVED",
            "action_version": 5,
            "next_allowed_commands": [],
            "approval_id": None,
            "attempt_id": None,
            "claim_token": None,
            "safe_error_code": "REAUTH_REQUIRED",
            "conflict_detail": "expired connection",
        },
    )

    assert decision["target"] == SupervisorTarget.REAUTH.value
    assert decision["next_phase"] is None
    assert decision["state_update"]["finalize_intent"] is None


def test_preflight_failure_blocks_even_with_approved_plan_id() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        plan_draft=_plan_draft("PLAN_READY"),
        approved_plan_id="approved-plan-1",
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PREFLIGHT,
        state=state,
        result={
            "applied": False,
            "result_code": "STATE_CONFLICT",
            "action_id": "action-write-1",
            "action_status": "APPROVED",
            "action_version": 5,
            "next_allowed_commands": [],
            "approval_id": None,
            "attempt_id": None,
            "claim_token": None,
            "safe_error_code": None,
            "conflict_detail": "write action requires an active approval",
        },
    )

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["reason_code"] == "STATE_CONFLICT"
    assert decision["state_update"]["workflow_phase"] == WorkflowPhase.FINALIZE.value
    assert decision["state_update"]["finalize_intent"] is not None
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
    finalize_intent = decision["state_update"]["finalize_intent"]
    assert finalize_intent is not None
    assert finalize_intent["intent"] == FinalizeIntent.COMPLETED.value
    restored_intent = derive_finalize_intent(state=_checkpoint_roundtrip(next_state))
    assert restored_intent is not None
    assert restored_intent["intent"] == FinalizeIntent.COMPLETED.value


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
    assert decision["budget_decision"] is not None
    assert decision["state_update"]["retry_budget"] is not None
    assert decision["budget_decision"]["decision"] == "ALLOW"
    assert decision["state_update"]["retry_budget"]["planning_revisions_used"] == 1


def test_second_revise_with_the_same_failure_signature_is_blocked() -> None:
    """G3 approve_semantic_revision dedup: same target Planning node (here
    planning.revise_answer, since answer_draft is set) + the same normalized
    Review failure signature must not get a second revision attempt, even
    though the planning_revisions_used cap (2) alone would still allow it."""
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )
    first = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )
    assert first["budget_decision"] is not None
    assert first["budget_decision"]["decision"] == "ALLOW"
    assert len(first["state_update"]["retry_budget"]["semantic_revision_signatures_used"]) == 1

    state_after_revision = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
        retry_budget=cast(RunBudgetV1, first["state_update"]["retry_budget"]),
    )

    second = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state_after_revision,
        result=_review_result("REVISE"),
    )

    assert second["target"] == SupervisorTarget.FINALIZE.value
    assert second["budget_decision"] is not None
    assert second["budget_decision"]["decision"] == "DENY"
    assert (
        second["budget_decision"]["budget_reason_code"]
        == BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED.value
    )
    assert second["state_update"]["finalize_intent"] is not None
    assert second["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value
    # planning_revisions_used must not have been consumed for a revision
    # attempt that never actually proceeds.
    assert first["state_update"]["retry_budget"]["planning_revisions_used"] == 1


def test_semantic_revision_dedup_survives_a_resumed_run() -> None:
    """G3 resume persistence: a retry_budget restored from checkpoint with
    the signature already recorded (as if the Run had revised, resumed
    after an interrupt, and re-entered Review with the identical failure)
    blocks the very first REVISE it sees in this invocation -- the dedup
    marker is read straight off the passed-in state, not any in-process
    cache."""
    restored_signature = build_semantic_failure_signature_v1(
        node_id="planning.revise_answer",
        failure_reason_codes=["PLAN_REQUIRED_ACTION_MISSING"],
    )
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
        retry_budget={
            **build_default_run_budget(),
            "semantic_revision_signatures_used": [restored_signature],
        },
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )

    assert decision["target"] == SupervisorTarget.FINALIZE.value
    assert decision["budget_decision"] is not None
    assert decision["budget_decision"]["decision"] == "DENY"
    assert (
        decision["budget_decision"]["budget_reason_code"]
        == BudgetReasonCode.SEMANTIC_SAME_FAILURE_LIMIT_EXHAUSTED.value
    )


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
    assert decision["budget_decision"] is not None
    assert decision["budget_decision"]["decision"] == "DENY"
    assert (
        decision["budget_decision"]["budget_reason_code"]
        == BudgetReasonCode.ADDITIONAL_ACQUISITION_LIMIT_EXHAUSTED.value
    )
    assert decision["state_update"]["finalize_intent"] is not None
    assert decision["state_update"]["finalize_intent"]["intent"] == FinalizeIntent.BLOCKED.value


def test_review_retrieve_more_with_frozen_route_becomes_retrieval_required() -> None:
    """Q2-HANDOFF: Review RETRIEVE_MORE -> RetrievalRequiredV1 -> Retrieval,
    only when a frozen IN Route already exists to retry within."""
    plan = _tool_route_plan()
    plan["input_plan"]["input_routes"] = [
        {
            "route_id": "route-1",
            "resource_type": "EMAIL",
            "connector_id": "google_workspace",
            "allowed_read_tool_ids": ["gmail.search_threads"],
            "required": True,
            "reason_codes": ["REQUIRED"],
        }
    ]
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )
    state["tool_route_plan"] = plan

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("RETRIEVE_MORE"),
    )

    assert decision["target"] == SupervisorTarget.CONTEXT_RETRIEVAL.value
    assert decision["next_phase"] == WorkflowPhase.CONTEXT_RETRIEVAL.value
    signal = decision["state_update"]["workflow_signal"]
    assert signal is not None
    assert signal["kind"] == "RETRIEVAL_REQUIRED"
    assert signal["needs"] == [
        {"required_information": "Need one more source.", "reason_codes": ["EVIDENCE_GAP"]}
    ]


def test_review_retrieve_more_without_frozen_route_becomes_route_reconsideration() -> None:
    """Q2-HANDOFF: Review RETRIEVE_MORE with no frozen IN Route to retry within
    -> RouteReconsiderationRequiredV1 -> Tool Route, not RetrievalRequiredV1."""
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )
    state["tool_route_plan"] = _tool_route_plan()  # input_routes == []

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("RETRIEVE_MORE"),
    )

    assert decision["target"] == SupervisorTarget.TOOL_ROUTE.value
    assert decision["next_phase"] == WorkflowPhase.TOOL_ROUTING.value
    signal = decision["state_update"]["workflow_signal"]
    assert signal is not None
    assert signal["kind"] == "ROUTE_RECONSIDERATION_REQUIRED"
    assert signal["reason_codes"] == ["RETRIEVAL_INPUT_ROUTE_UNAVAILABLE", "EVIDENCE_GAP"]
    assert decision["reason_code"] == "RETRIEVAL_INPUT_ROUTE_UNAVAILABLE"


def test_solution_planning_route_reconsideration_required_routes_to_tool_route() -> None:
    state = _state(workflow_phase=WorkflowPhase.SOLUTION_PLANNING)
    result = _answer_draft("ANSWER_ONLY")
    result["status"] = "ROUTE_RECONSIDERATION_REQUIRED"
    result["reason_codes"] = ["NEW_RESOURCE_ROUTE_REQUIRED"]

    decision = route_supervisor(
        phase=WorkflowPhase.SOLUTION_PLANNING,
        state=state,
        result=result,
    )

    assert decision["target"] == SupervisorTarget.TOOL_ROUTE.value
    assert decision["next_phase"] == WorkflowPhase.TOOL_ROUTING.value
    signal = decision["state_update"]["workflow_signal"]
    assert signal is not None
    assert signal["kind"] == "ROUTE_RECONSIDERATION_REQUIRED"
    assert signal["reason_codes"] == ["NEW_RESOURCE_ROUTE_REQUIRED"]
    assert decision["state_update"]["answer_draft"] is None
    assert decision["state_update"]["plan_draft"] is None


def test_review_route_reconsideration_routes_to_tool_route() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        answer_draft=_answer_draft("ANSWER_ONLY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("ROUTE_RECONSIDERATION"),
    )

    assert decision["target"] == SupervisorTarget.TOOL_ROUTE.value
    assert decision["next_phase"] == WorkflowPhase.TOOL_ROUTING.value
    signal = decision["state_update"]["workflow_signal"]
    assert signal is not None
    assert signal["kind"] == "ROUTE_RECONSIDERATION_REQUIRED"
    assert decision["state_update"]["plan_review"] is None


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

    assert decision["state_update"]["finalize_intent"] is not None
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
    assert decision["state_update"]["finalize_intent"] is not None
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
    request_intent: RequestIntentV2 | None = None,
    acquisition_result: AcquisitionResultV1 | None = None,
    context_result: ContextRetrievalResultV1 | None = None,
    answer_draft: AnswerDraftV1 | None = None,
    plan_draft: ActionPlanDraftV1 | None = None,
    plan_review: PlanReviewResultV1 | None = None,
    approved_plan_id: str | None = None,
    retry_budget: RunBudgetV1 | None = None,
) -> MultiAgentGraphState:
    return {
        "schema_version": 1,
        "run_id": "run-1",
        "conversation_id": "conv-1",
        "thread_id": "thread-1",
        "workflow_phase": workflow_phase.value,
        "request_intent": request_intent,
        "tool_route_plan": None,
        "workflow_signal": None,
        "source_fetch_plans": [],
        "acquisition_result": acquisition_result,
        "context_result": context_result,
        "work_analysis_result": None,
        "answer_draft": answer_draft,
        "plan_draft": plan_draft,
        "plan_review": plan_review,
        "approved_plan_id": approved_plan_id,
        "execution_summary": None,
        "verification_summary": None,
        "finalize_intent": None,
        "user_interrupt": None,
        "retry_budget": retry_budget or build_default_run_budget(),
        "prompt_context": {},
        "trace_context": {},
    }


def _request_intent() -> RequestIntentV2:
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "Summarize the latest status.",
        "completion_conditions": ["Provide the latest status."],
        "constraints": [],
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
        "requested_effect_hints": ["READ"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
    }


def _tool_route_plan() -> dict[str, object]:
    meta = {"artifact_id": "route-plan-1", "revision": 1, "based_on": []}
    return {
        "schema_version": 2,
        "input_plan": {"schema_version": 1, "meta": meta, "input_routes": []},
        "output_plan": {"schema_version": 1, "meta": meta, "output_mode": "ANSWER"},
        "tool_registry_version": "2026-08-06.p0",
    }


def _acquisition_result(
    status: Literal[
        "COMPLETE",
        "PARTIAL",
        "AUTH_REQUIRED",
        "RATE_LIMITED",
        "BUDGET_EXHAUSTED",
        "FAILED",
    ],
) -> AcquisitionResultV1:
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


def _context_result(
    status: Literal["SUFFICIENT", "NEEDS_MORE_DATA", "NEEDS_CONFIRMATION", "PARTIAL", "BLOCKED"],
) -> ContextRetrievalResultV1:
    additional_request: AdditionalAcquisitionRequestV1 | None = None
    ambiguity: dict[str, object] | None = None
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


def _answer_draft(
    status: Literal["ANSWER_ONLY", "NEEDS_CONFIRMATION", "BLOCKED"],
) -> AnswerDraftV1:
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


def _plan_draft(
    status: Literal["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
) -> ActionPlanDraftV1:
    return {
        "schema_version": 2,
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


def _action_draft() -> ActionDraftV1:
    return {
        "schema_version": 2,
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


def _review_result(
    status: Literal["PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"],
) -> PlanReviewResultV1:
    request: AdditionalAcquisitionRequestV1 | None = None
    confirmation: dict[str, object] | None = None
    issues: list[ReviewIssueV1] = []
    blockers = []
    if status == "REVISE":
        issues = [
            {
                "schema_version": 2,
                "issue_id": "issue-1",
                "kind": "MISSING_GOAL_COVERAGE",
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
                "schema_version": 2,
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
    if status == "ROUTE_RECONSIDERATION":
        issues = [
            {
                "schema_version": 2,
                "issue_id": "issue-1",
                "kind": "ROUTE_CANNOT_SATISFY_REQUEST",
                "message": "The fixed route cannot satisfy the request",
                "affected_action_ids": [],
                "affected_field_paths": ["answer"],
                "evidence_refs": ["evidence-1"],
                "resource_refs": ["message:1"],
                "reason_codes": ["ROUTE_CANNOT_SATISFY_REQUEST"],
            }
        ]
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
        "schema_version": 2,
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
    state_update: GraphStateUpdateV1,
) -> MultiAgentGraphState:
    updated = state.copy()
    updated.update(state_update)
    return updated


def _checkpoint_roundtrip(state: MultiAgentGraphState) -> MultiAgentGraphState:
    decoded: object = json.loads(json.dumps(state))
    if decoded != state:
        raise AssertionError("checkpoint roundtrip changed graph state")
    return cast(MultiAgentGraphState, decoded)
