"""Deterministic Work Analysis, Planning, and Review Supervisor rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    base_supervisor_state_update,
    make_supervisor_decision,
    recovery_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_result_contracts import (
    PlanningRouteResultV1,
    WorkAnalysisRouteResultV1,
)
from google_work_agent.adapters.langgraph.main.supervisor_retrieval_rules import (
    route_retrieval_required,
)
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    budget_reason_code,
    confirmation_state_update,
    finalize_supervisor_result,
    request_intent_from_state,
    review_target_from_state,
)
from google_work_agent.application.agents.planning.contracts.planning_result import (
    PlanningResultV2,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
    ReviewBlockV2,
    ReviewConfirmV2,
    ReviewRetrieveMoreV2,
    ReviewReviseV2,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    approve_planning_revision,
    approve_semantic_revision,
    build_semantic_failure_signature_v1,
)
from google_work_agent.application.use_cases.run.terminal_contract import (
    FinalizeIntent,
    ReviewResult,
)
from google_work_agent.ports.system.contracts.additional_acquisition import (
    AdditionalAcquisitionRequestV1,
)


def route_work_analysis(
    *,
    state: GraphState,
    result: WorkAnalysisRouteResultV1,
) -> SupervisorDecisionV1:
    disposition = result.get("disposition")
    reason_codes = [code for code in result.get("reason_codes", []) if code]
    if disposition == "COMPLETE":
        artifact = result.get("typed_result")
        if artifact is None:
            return recovery_supervisor_decision("WORK_ANALYSIS_RESULT_MISSING")
        return make_supervisor_decision(
            target=SupervisorTarget.SOLUTION_PLANNING,
            next_phase=WorkflowPhase.SOLUTION_PLANNING,
            state_update=base_supervisor_state_update(
                WorkflowPhase.SOLUTION_PLANNING,
                work_analysis_result=artifact,
                workflow_signal=None,
            ),
            reason_code="WORK_ANALYSIS_COMPLETE",
        )
    if disposition == "NEEDS_MORE_DATA":
        signal = result.get("workflow_signal")
        if not isinstance(signal, Mapping) or signal.get("kind") != "RETRIEVAL_REQUIRED":
            return recovery_supervisor_decision("WORK_ANALYSIS_RETRIEVAL_SIGNAL_INVALID")
        needs = signal.get("needs")
        if not isinstance(needs, list) or not needs:
            return recovery_supervisor_decision("WORK_ANALYSIS_RETRIEVAL_NEEDS_MISSING")
        request: AdditionalAcquisitionRequestV1 = {
            "schema_version": 1,
            "origin_phase": WorkflowPhase.WORK_ANALYSIS.value,
            "origin_result": "NEEDS_MORE_DATA",
            "missing_slots": [],
            "missing_information": [
                str(need["required_information"])
                for need in needs
                if isinstance(need, Mapping) and need.get("required_information")
            ],
            "evidence_refs": [],
            "reason_codes": reason_codes or list(cast(list[str], signal.get("reason_codes", []))),
        }
        return route_retrieval_required(
            state=state,
            reason_code=(reason_codes or ["WORK_ANALYSIS_NEEDS_MORE_DATA"])[0],
            current_update={"work_analysis_result": None},
            request=request,
        )
    if disposition == "BLOCKED":
        return finalize_supervisor_result(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=(reason_codes or ["WORK_ANALYSIS_BLOCKED"])[0],
            work_analysis_result=None,
            workflow_signal=None,
        )
    return recovery_supervisor_decision("WORK_ANALYSIS_CONTRACT_VIOLATION")


def route_planning(
    *,
    state: GraphState,
    result: PlanningRouteResultV1,
) -> SupervisorDecisionV1:
    disposition = result.get("disposition")
    artifact = result.get("typed_result")
    reason_codes = [code for code in result.get("reason_codes", []) if code]
    if disposition == "ANSWER_ONLY":
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("answer"), str):
            return recovery_supervisor_decision("PLANNING_ANSWER_RESULT_INVALID")
        return make_supervisor_decision(
            target=SupervisorTarget.RESPONSE_SYNTHESIS,
            next_phase=WorkflowPhase.RESPONSE_SYNTHESIS,
            state_update=base_supervisor_state_update(
                WorkflowPhase.RESPONSE_SYNTHESIS,
                planning_result=cast(PlanningResultV2, artifact),
                workflow_signal=None,
            ),
            reason_code="ANSWER_ONLY_RESPONSE_READY",
        )
    if disposition == "PLAN_READY":
        if not isinstance(artifact, Mapping) or not isinstance(artifact.get("actions"), list):
            return recovery_supervisor_decision("PLANNING_ACTION_RESULT_INVALID")
        return make_supervisor_decision(
            target=SupervisorTarget.PLAN_REVIEW_INSPECT,
            next_phase=WorkflowPhase.PLAN_REVIEW,
            state_update=base_supervisor_state_update(
                WorkflowPhase.PLAN_REVIEW,
                planning_result=cast(PlanningResultV2, artifact),
                workflow_signal=None,
            ),
            reason_code="PLAN_READY",
        )
    if disposition == "BLOCKED":
        return finalize_supervisor_result(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=(reason_codes or ["PLANNING_BLOCKED"])[0],
            planning_result=None,
            plan_review=None,
        )
    return recovery_supervisor_decision("PLANNING_CONTRACT_VIOLATION")


def route_plan_review(
    *,
    state: GraphState,
    result: PlanReviewResultV2,
) -> SupervisorDecisionV1:
    status = ReviewResult(str(result["status"]))
    review_update: GraphStateUpdateV1 = {"plan_review": result}
    if status is ReviewResult.PASS:
        target_kind = review_target_from_state(state)
        if target_kind == "ANSWER":
            return finalize_supervisor_result(
                state=state,
                intent=FinalizeIntent.COMPLETED.value,
                reason_code="ANSWER_ONLY_REVIEW_PASS",
                current_update=review_update,
            )
        return make_supervisor_decision(
            target=SupervisorTarget.DOMAIN_VALIDATION,
            next_phase=WorkflowPhase.DOMAIN_VALIDATION,
            state_update=base_supervisor_state_update(
                WorkflowPhase.DOMAIN_VALIDATION,
                current_update=review_update,
            ),
            reason_code="PLAN_REVIEW_PASS",
        )
    if status is ReviewResult.REVISE:
        return _route_review_revision(state=state, result=result, current_update=review_update)
    if status is ReviewResult.RETRIEVE_MORE:
        retrieval_result = cast(ReviewRetrieveMoreV2, result)
        reason_codes = list(dict.fromkeys(gap["code"] for gap in retrieval_result["evidence_gaps"]))
        missing_information = [
            information
            for gap in retrieval_result["evidence_gaps"]
            for information in gap["required_information"]
        ]
        return route_retrieval_required(
            state=state,
            reason_code="PLAN_REVIEW_RETRIEVE_MORE",
            current_update=review_update,
            request={
                "schema_version": 1,
                "origin_phase": WorkflowPhase.PLAN_REVIEW.value,
                "origin_result": ReviewResult.RETRIEVE_MORE.value,
                "missing_slots": [],
                "missing_information": list(dict.fromkeys(missing_information)),
                "evidence_refs": [],
                "reason_codes": reason_codes,
            },
        )
    if status is ReviewResult.CONFIRM:
        confirmation = cast(ReviewConfirmV2, result)["confirmation"]
        question: request_understanding_output.ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "review.aggregate_findings",
            "question": confirmation["question"],
            "affected_field_paths": [],
            "reason_code": "PLAN_REVIEW_CONFIRM",
            "known_context_summary": str(
                request_intent_from_state(state).get("goal", "Plan review")
            ),
            "options": [
                {"option_id": option, "label": option} for option in confirmation["options"]
            ],
        }
        return make_supervisor_decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=confirmation_state_update(question=question, **review_update),
            reason_code=question["reason_code"],
        )
    blocked_result = cast(ReviewBlockV2, result)
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=blocked_result["blockers"][0]["code"],
        current_update=review_update,
    )


def _route_review_revision(
    *,
    state: GraphState,
    result: PlanReviewResultV2,
    current_update: GraphStateUpdateV1,
) -> SupervisorDecisionV1:
    revised_result = cast(ReviewReviseV2, result)
    revision_budget = approve_planning_revision(state["retry_budget"])
    if revision_budget["decision"] == BudgetDecision.DENY.value:
        return finalize_supervisor_result(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=budget_reason_code(
                revision_budget,
                default="PLANNING_REVISION_DENIED",
            ),
            budget_decision=revision_budget,
            current_update=current_update,
        )
    target_kind = review_target_from_state(state)
    node_id = "planning.revise_answer" if target_kind == "ANSWER" else "planning.revise_plan"
    failure_reason_codes = [issue["code"] for issue in revised_result["issues"]]
    if failure_reason_codes:
        signature = build_semantic_failure_signature_v1(
            node_id=node_id,
            failure_reason_codes=failure_reason_codes,
        )
        budget = approve_semantic_revision(revision_budget["run_budget"], signature=signature)
        if budget["decision"] == BudgetDecision.DENY.value:
            return finalize_supervisor_result(
                state=state,
                intent=FinalizeIntent.BLOCKED.value,
                reason_code=budget_reason_code(budget, default="SEMANTIC_REVISION_DENIED"),
                budget_decision=budget,
                current_update=current_update,
            )
    else:
        budget = revision_budget
    target = (
        SupervisorTarget.PLANNING_REVISE_ANSWER
        if target_kind == "ANSWER"
        else SupervisorTarget.PLANNING_REVISE_PLAN
    )
    return make_supervisor_decision(
        target=target,
        next_phase=WorkflowPhase.SOLUTION_PLANNING,
        state_update=base_supervisor_state_update(
            WorkflowPhase.SOLUTION_PLANNING,
            retry_budget=budget["run_budget"],
            current_update=current_update,
        ),
        reason_code="PLAN_REVIEW_REVISE",
        budget_decision=budget,
    )


__all__ = ["route_plan_review", "route_planning", "route_work_analysis"]
