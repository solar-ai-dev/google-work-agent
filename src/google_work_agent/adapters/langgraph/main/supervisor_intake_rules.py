"""Deterministic initialization, intent, and frozen-route Supervisor rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.confirmation_projection import (
    validate_clarification_question_v1,
)
from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    RequestUnderstandingResult,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    is_work_analysis_required,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    base_supervisor_state_update,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    JsonObject,
    confirmation_state_update,
    finalize_supervisor_result,
    request_intent_from_state,
    request_invalid_reason_code,
)
from google_work_agent.application.agents.request_understanding.contracts import (
    request_understanding_output,
)
from google_work_agent.application.agents.review.contracts.plan_review_result import (
    PlanReviewResultV2,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRouteDisposition,
    ToolRoutePlanV2,
    ToolRouteResultV1,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetProfile,
    RunBudgetV2,
    promote_run_budget_profile,
)
from google_work_agent.application.use_cases.run.terminal_contract import FinalizeIntent
from google_work_agent.ports.system.contracts.workflow_signal import (
    RouteReconsiderationRequiredV1,
)


def route_initialize(result: JsonObject) -> SupervisorDecisionV1:
    if result.get("current_status") == "ANALYZING":
        return make_supervisor_decision(
            target=SupervisorTarget.REQUEST_UNDERSTANDING,
            next_phase=WorkflowPhase.REQUEST_ANALYSIS,
            state_update={"workflow_phase": WorkflowPhase.REQUEST_ANALYSIS.value},
            reason_code="REQUEST_UNDERSTANDING_REQUIRED",
        )
    return make_supervisor_decision(
        target=SupervisorTarget.DOMAIN_RECONCILE,
        next_phase=WorkflowPhase.INITIALIZE,
        state_update={"workflow_phase": WorkflowPhase.INITIALIZE.value},
        reason_code=str(result.get("current_status") or "INITIALIZE_NOT_APPLIED"),
    )


def route_reconsideration(
    phase: WorkflowPhase,
    result: object | None,
) -> SupervisorDecisionV1 | None:
    if not isinstance(result, Mapping):
        return None
    status = result.get("disposition", result.get("status", result.get("result")))
    expected = {
        WorkflowPhase.CONTEXT_RETRIEVAL: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.WORK_ANALYSIS: "ROUTE_RECONSIDERATION_REQUIRED",
        WorkflowPhase.PLAN_REVIEW: "ROUTE_RECONSIDERATION",
    }.get(phase)
    if expected is None or status != expected:
        return None
    raw_reason_codes = result.get("reason_codes", [])
    if phase is WorkflowPhase.PLAN_REVIEW:
        route_issues = result.get("route_issues", [])
        raw_reason_codes = (
            [
                item["code"]
                for item in route_issues
                if isinstance(item, Mapping) and isinstance(item.get("code"), str)
            ]
            if isinstance(route_issues, list)
            else []
        )
    reason_codes = (
        [item for item in raw_reason_codes if isinstance(item, str)]
        if isinstance(raw_reason_codes, list)
        else []
    )
    signal: RouteReconsiderationRequiredV1 = {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": reason_codes or ["ROUTE_RECONSIDERATION_REQUIRED"],
    }
    review_update = (
        {"plan_review": cast(PlanReviewResultV2, result)}
        if phase is WorkflowPhase.PLAN_REVIEW
        else {"plan_review": None}
    )
    return make_supervisor_decision(
        target=SupervisorTarget.TOOL_ROUTE,
        next_phase=WorkflowPhase.TOOL_ROUTING,
        state_update=base_supervisor_state_update(
            WorkflowPhase.TOOL_ROUTING,
            workflow_signal=signal,
            acquisition_result=None,
            retrieval_result=None,
            work_analysis_result=None,
            planning_result=None,
            **review_update,
        ),
        reason_code=signal["reason_codes"][0],
    )


def route_request_understanding(
    *,
    state: GraphState,
    output: request_understanding_output.RequestUnderstandingOutputV1,
) -> SupervisorDecisionV1:
    result = RequestUnderstandingResult(output["result"])
    request_intent = output.get("request_intent")
    if result is RequestUnderstandingResult.COMPLETE:
        return make_supervisor_decision(
            target=SupervisorTarget.TOOL_ROUTE,
            next_phase=WorkflowPhase.TOOL_ROUTING,
            state_update=base_supervisor_state_update(
                WorkflowPhase.TOOL_ROUTING,
                request_intent=request_intent,
            ),
        )
    if result is RequestUnderstandingResult.NEEDS_CONFIRMATION:
        question = validate_clarification_question_v1(output["clarification"])
        return make_supervisor_decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=confirmation_state_update(
                question=question,
                request_intent=request_intent,
            ),
            reason_code=question["reason_code"],
        )
    reason_code = request_invalid_reason_code(output)
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=reason_code,
        request_intent=request_intent,
    )


def route_tool_routing(
    *,
    state: GraphState,
    result: ToolRouteResultV1,
) -> SupervisorDecisionV1:
    try:
        disposition = ToolRouteDisposition(result["disposition"])
    except (KeyError, ValueError):
        return make_supervisor_decision(
            target=SupervisorTarget.RECOVERY,
            next_phase=WorkflowPhase.RECOVERY,
            state_update=base_supervisor_state_update(WorkflowPhase.RECOVERY),
            reason_code="TOOL_ROUTE_CONTRACT_VIOLATION",
        )
    plan = result["tool_route_plan"]
    if disposition in {
        ToolRouteDisposition.ROUTE_READY,
        ToolRouteDisposition.NO_TOOL_NEEDED,
    }:
        if plan is None:
            return make_supervisor_decision(
                target=SupervisorTarget.RECOVERY,
                next_phase=WorkflowPhase.RECOVERY,
                state_update=base_supervisor_state_update(WorkflowPhase.RECOVERY),
                reason_code="TOOL_ROUTE_PLAN_MISSING",
            )
        return route_frozen_tool_plan(state=state, plan=plan, disposition=disposition)
    if disposition is ToolRouteDisposition.NEEDS_CONFIRMATION:
        question: request_understanding_output.ClarificationQuestionV1 = {
            "schema_version": 1,
            "origin_target": "tool_route.finalize",
            "question": "작업 대상 또는 작업 종류를 더 구체적으로 알려주세요.",
            "affected_field_paths": [
                "requested_resource_hints",
                "requested_effect_hints",
            ],
            "reason_code": result["reason_codes"][0]
            if result["reason_codes"]
            else "TOOL_ROUTE_NEEDS_CONFIRMATION",
            "known_context_summary": request_intent_from_state(state)["goal"],
            "options": [],
        }
        return make_supervisor_decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            next_phase=WorkflowPhase.WAITING_CONFIRMATION,
            state_update=confirmation_state_update(
                question=question,
                tool_route_plan=None,
                workflow_signal=result["workflow_signal"],
            ),
            reason_code=question["reason_code"],
        )
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=result["reason_codes"][0]
        if result["reason_codes"]
        else "TOOL_ROUTE_BLOCKED",
        tool_route_plan=None,
        workflow_signal=result["workflow_signal"],
    )


def route_frozen_tool_plan(
    *,
    state: GraphState,
    plan: ToolRoutePlanV2,
    disposition: ToolRouteDisposition,
) -> SupervisorDecisionV1:
    if plan["input_plan"]["input_routes"]:
        return make_supervisor_decision(
            target=SupervisorTarget.CONTEXT_RETRIEVAL,
            next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
            state_update=base_supervisor_state_update(
                WorkflowPhase.CONTEXT_RETRIEVAL,
                tool_route_plan=plan,
                workflow_signal=None,
                retry_budget=_retrieval_route_budget(state),
            ),
            reason_code=disposition.value,
        )
    if is_work_analysis_required(state=state, plan=plan):
        return make_supervisor_decision(
            target=SupervisorTarget.WORK_ANALYSIS,
            next_phase=WorkflowPhase.WORK_ANALYSIS,
            state_update=base_supervisor_state_update(
                WorkflowPhase.WORK_ANALYSIS,
                tool_route_plan=plan,
                workflow_signal=None,
            ),
            reason_code="RETRIEVAL_NOT_REQUIRED",
        )
    return make_supervisor_decision(
        target=SupervisorTarget.SOLUTION_PLANNING,
        next_phase=WorkflowPhase.SOLUTION_PLANNING,
        state_update=base_supervisor_state_update(
            WorkflowPhase.SOLUTION_PLANNING,
            tool_route_plan=plan,
            workflow_signal=None,
        ),
        reason_code="RETRIEVAL_AND_WORK_ANALYSIS_NOT_REQUIRED",
    )


def _retrieval_route_budget(state: GraphState) -> RunBudgetV2:
    return promote_run_budget_profile(state["retry_budget"], BudgetProfile.RETRIEVAL_HEAVY)


__all__ = [
    "route_initialize",
    "route_reconsideration",
    "route_request_understanding",
    "route_tool_routing",
]
