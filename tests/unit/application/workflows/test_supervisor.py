import json
from typing import Literal, cast

import pytest

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor import (
    SupervisorTarget,
    route_supervisor,
)
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
    PlannedActionV2,
)
from google_work_agent.application.agents.planning.contracts.answer_draft import AnswerDraftV2
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationResult,
)
from google_work_agent.application.agents.planning.contracts.planning_result import PlanningResultV2
from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    RequestIntentV2,
)
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    RetrievalResultV1,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.state_artifact import StateArtifactMetaV1
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    WriteActionResponse,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    RETRIEVAL_HEAVY_MAX_LLM_CALLS,
    BudgetProfile,
    BudgetReasonCode,
    RunBudgetV2,
    approve_semantic_revision,
    build_default_run_budget,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.use_cases.run.run_terminal import derive_finalize_intent
from google_work_agent.application.use_cases.run.terminal_contract import (
    FinalizeIntent,
)


def test_request_complete__routes_to__tool_route() -> None:
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


def test_tool_route_ready__enters_retrieval_for__initial_query_planning() -> None:
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


def test_unknown_tool__route_disposition_fails__closed_to_recovery() -> None:
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


def test_work_analysis__routing_is_owned__by_canonical_subgraph() -> None:
    state = _state(workflow_phase=WorkflowPhase.WORK_ANALYSIS)

    with pytest.raises(ValueError, match="canonical eight-node subgraph"):
        route_supervisor(
            phase=WorkflowPhase.WORK_ANALYSIS,
            state=state,
            result={},
        )


def test_review_pass__with_plan_routes__to_domain_validation() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_domain_validation__require_approval_routes__to_waiting_approval() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.DOMAIN_VALIDATION,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_domain_validation__block_finalizes__with_blocked_intent() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.DOMAIN_VALIDATION,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_preflight_write__claim_routes__to_action_execution() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_preflight_reauth__required_routes__to_reauth_boundary() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_preflight_failure__blocks_even_with__approved_plan_id() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PREFLIGHT,
        planning_result=_plan_draft("PLAN_READY"),
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


def test_review_pass_with__answer_creates_checkpoint__safe_finalize_intent() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
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


def test_review_revise_routes__answer_draft_to_revise__answer_with_shared_budget() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
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


def test_second_revise_with__the_same_failure__signature_is_blocked() -> None:
    """G3 approve_semantic_revision dedup: same target Planning node (here
    planning.revise_answer, since answer_draft is set) + the same normalized
    Review failure signature must not get a second revision attempt, even
    though the planning_revisions_used cap (2) alone would still allow it."""
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
    )
    first = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )
    assert first["budget_decision"] is not None
    assert first["budget_decision"]["decision"] == "ALLOW"
    assert len(first["state_update"]["retry_budget"]["semantic_revisions_used_by_failure"]) == 1

    state_after_revision = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
        retry_budget=cast(RunBudgetV2, first["state_update"]["retry_budget"]),
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


def test_semantic_revision__dedup_survives__a_resumed_run() -> None:
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
    restored_budget = approve_semantic_revision(
        build_default_run_budget(), signature=restored_signature
    )["run_budget"]
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
        retry_budget=restored_budget,
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


def test_review_revise__routes_plan_draft__to_revise_plan() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_plan_draft("PLAN_READY"),
    )

    decision = route_supervisor(
        phase=WorkflowPhase.PLAN_REVIEW,
        state=state,
        result=_review_result("REVISE"),
    )

    assert decision["target"] == SupervisorTarget.PLANNING_REVISE_PLAN.value
    assert decision["next_phase"] == WorkflowPhase.SOLUTION_PLANNING.value
    assert decision["state_update"]["retry_budget"]["planning_revisions_used"] == 1


def test_review_retrieve_more__budget_deny_blocks__instead_of_guessing_failure() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
        retry_budget={
            **build_default_run_budget(),
            "additional_retrieval_rounds_used": 2,
            "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
            "llm_call_limit": RETRIEVAL_HEAVY_MAX_LLM_CALLS,
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


def test_review_retrieve_more__with_frozen_route__becomes_retrieval_required() -> None:
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
        planning_result=_answer_draft("ANSWER_ONLY"),
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


def test_review_retrieve_more__without_frozen_route__becomes_route_reconsideration() -> None:
    """Q2-HANDOFF: Review RETRIEVE_MORE with no frozen IN Route to retry within
    -> RouteReconsiderationRequiredV1 -> Tool Route, not RetrievalRequiredV1."""
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
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


def test_review_route__reconsideration_routes__to_tool_route() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
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
    assert decision["state_update"]["plan_review"] == _review_result("ROUTE_RECONSIDERATION")


def test_additional_acquisition_budget__deny_preserves_partial__result_kind_when_present() -> None:
    state = _state(
        workflow_phase=WorkflowPhase.PLAN_REVIEW,
        planning_result=_answer_draft("ANSWER_ONLY"),
        retrieval_result=cast(
            RetrievalResultV1,
            {"coverage": "PARTIAL", "evidence_refs": ["evidence-1"]},
        ),
        retry_budget={
            **build_default_run_budget(),
            "additional_retrieval_rounds_used": 2,
            "profile": BudgetProfile.RETRIEVAL_HEAVY.value,
            "llm_call_limit": RETRIEVAL_HEAVY_MAX_LLM_CALLS,
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


def test_request_invalid__routes_to__blocked_finalize() -> None:
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


def test_recovery_phase__routes_to__recovery_boundary() -> None:
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
    retrieval_result: RetrievalResultV1 | None = None,
    planning_result: PlanningResultV2 | None = None,
    plan_review: PlanReviewResultV2 | None = None,
    approved_plan_id: str | None = None,
    retry_budget: RunBudgetV2 | None = None,
) -> GraphState:
    return cast(
        GraphState,
        {
            "schema_version": 2,
            "run_id": "run-1",
            "conversation_id": "conv-1",
            "langgraph_thread_id": "thread-1",
            "workflow_phase": workflow_phase.value,
            "graph_profile": "THREE_STAGE",
            "graph_version": "test-graph-v1",
            "run_input": {
                "entry_mode": "AGENT_SEARCH",
                "user_request": "Summarize the latest status.",
                "selected_resource_refs": [],
                "requested_mode": "AUTO",
            },
            "request_intent": request_intent,
            "tool_route_plan": None,
            "workflow_signal": None,
            "acquisition_result": None,
            "retrieval_result": retrieval_result,
            "work_analysis_result": None,
            "planning_result": planning_result,
            "plan_review": plan_review,
            "approved_plan_id": approved_plan_id,
            "execution_summary": None,
            "verification_summary": None,
            "finalize_intent": None,
            "terminal_commit_intent": None,
            "user_interrupt": None,
            "policy_confirmation_receipts": [],
            "retry_budget": retry_budget or build_default_run_budget(),
            "prompt_context": {},
            "trace_context": {},
            "__target__": "supervisor",
            "__logical_target__": "supervisor",
        },
    )


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


def _tool_route_plan() -> ToolRoutePlanV2:
    meta: StateArtifactMetaV1 = {
        "artifact_id": "route-plan-1",
        "revision": 1,
        "based_on": [],
    }
    return {
        "schema_version": 2,
        "input_plan": {"schema_version": 1, "meta": meta, "input_routes": []},
        "output_plan": {"schema_version": 1, "meta": meta, "output_mode": "ANSWER"},
        "tool_registry_version": "2026-08-06.p0",
    }


def _answer_draft(
    status: Literal["ANSWER_ONLY", "NEEDS_CONFIRMATION", "BLOCKED"],
) -> AnswerDraftV2:
    del status
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "answer-1", "revision": 1, "based_on": []},
        "answer": "Here is the answer.",
        "evidence_refs": ["evidence-1"],
    }


def _plan_draft(
    status: Literal["PLAN_READY", "NEEDS_CONFIRMATION", "BLOCKED"],
) -> ActionPlanDraftV2:
    del status
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "plan-1", "revision": 1, "based_on": []},
        "actions": [_action_draft()],
    }


def _action_draft() -> PlannedActionV2:
    return {
        "action_id": "action-1",
        "route_id": "route-1",
        "effect": "CREATE",
        "tool_id": "tasks_create_task",
        "arguments": {"task_list_id": "list-1", "payload": {"title": "Follow up"}},
        "evidence_refs": ["evidence-1"],
        "depends_on_action_ids": [],
    }


def _review_result(
    status: Literal["PASS", "REVISE", "RETRIEVE_MORE", "ROUTE_RECONSIDERATION", "CONFIRM", "BLOCK"],
) -> PlanReviewResultV2:
    meta = {"artifact_id": "review-1", "revision": 1, "based_on": []}
    result: dict[str, object] = {
        "schema_version": 2,
        "meta": meta,
        "status": status,
    }
    if status == "PASS":
        result["summary"] = "Review summary"
    if status == "REVISE":
        result["issues"] = [
            {
                "code": "PLAN_REQUIRED_ACTION_MISSING",
                "description": "Missing one point",
                "affected_dimensions": ["review.inspect_goal_and_evidence"],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "evidence_refs": ["evidence-1"],
            }
        ]
    if status == "RETRIEVE_MORE":
        result["evidence_gaps"] = [
            {
                "code": "EVIDENCE_GAP",
                "description": "Need more evidence",
                "required_information": ["Need one more source."],
            }
        ]
    if status == "ROUTE_RECONSIDERATION":
        result["route_issues"] = [
            {
                "code": "ROUTE_CANNOT_SATISFY_REQUEST",
                "description": "The fixed route cannot satisfy the request",
                "affected_route_ids": [],
            }
        ]
    if status == "CONFIRM":
        result["confirmation"] = {
            "question": "Which interpretation is correct?",
            "options": ["first", "second"],
        }
    if status == "BLOCK":
        result["blockers"] = [
            {
                "code": "POLICY_BLOCKER",
                "description": "policy blocker",
                "affected_action_ids": [],
            }
        ]
    return cast(PlanReviewResultV2, result)


def _apply_state_update(
    state: GraphState,
    state_update: GraphStateUpdateV1,
) -> GraphState:
    updated = state.copy()
    updated.update(state_update)
    return updated


def _checkpoint_roundtrip(state: GraphState) -> GraphState:
    decoded: object = json.loads(json.dumps(state))
    if decoded != state:
        raise AssertionError("checkpoint roundtrip changed graph state")
    return cast(GraphState, decoded)
