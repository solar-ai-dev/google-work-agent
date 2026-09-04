"""Deterministic Retrieval handoff and bounded back-edge rules."""

from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
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
from google_work_agent.adapters.langgraph.main.supervisor_result_contracts import (
    RetrievalRouteResultV1,
)
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    budget_reason_code,
    finalize_supervisor_result,
    has_supported_evidence,
)
from google_work_agent.application.agents.retrieval.assess_sufficiency import (
    InsufficientDataContext,
    InsufficientDataDisposition,
    InsufficientDataIssue,
    ResolutionSource,
    decide_insufficient_data,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    BudgetDecision,
    approve_additional_acquisition,
)
from google_work_agent.application.use_cases.run.terminal_contract import FinalizeIntent
from google_work_agent.ports.system.contracts.additional_acquisition import (
    AdditionalAcquisitionRequestV1,
)
from google_work_agent.ports.system.contracts.workflow_signal import (
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
)


def route_retrieval(
    *,
    state: GraphState,
    retrieval_return: RetrievalRouteResultV1,
) -> SupervisorDecisionV1:
    """Route only Retrieval's canonical return artifact and disposition."""

    disposition = retrieval_return["disposition"]
    retrieval_result = retrieval_return["typed_result"]
    if disposition in {"SUFFICIENT", "PARTIAL"}:
        if retrieval_result is None:
            raise ValueError("successful Retrieval return requires its typed result")
        retrieval_update: GraphStateUpdateV1 = {"retrieval_result": retrieval_result}
        plan = state.get("tool_route_plan")
        if plan is None:
            raise ValueError("successful Retrieval return requires its frozen tool route plan")
        if not is_work_analysis_required(state=state, plan=plan):
            return make_supervisor_decision(
                target=SupervisorTarget.SOLUTION_PLANNING,
                next_phase=WorkflowPhase.SOLUTION_PLANNING,
                state_update=base_supervisor_state_update(
                    WorkflowPhase.SOLUTION_PLANNING,
                    current_update=retrieval_update,
                ),
                reason_code="WORK_ANALYSIS_NOT_REQUIRED",
            )
        return make_supervisor_decision(
            target=SupervisorTarget.WORK_ANALYSIS,
            next_phase=WorkflowPhase.WORK_ANALYSIS,
            state_update=base_supervisor_state_update(
                WorkflowPhase.WORK_ANALYSIS,
                current_update=retrieval_update,
            ),
            reason_code=disposition,
        )
    if disposition == "NEEDS_MORE_DATA":
        raise ValueError("Retrieval NEEDS_MORE_DATA must remain inside its bounded local loop")
    if disposition == "NEEDS_CONFIRMATION":
        raise ValueError("Retrieval confirmation must be handled at its owner checkpoint")
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code="CONTEXT_BLOCKED",
    )


def route_retrieval_required(
    *,
    state: GraphState,
    reason_code: str,
    current_update: GraphStateUpdateV1,
    request: AdditionalAcquisitionRequestV1 | None,
) -> SupervisorDecisionV1:
    """Re-enter a frozen Retrieval route under the shared bounded budget."""

    if request is None:
        raise ValueError("retrieval-required route requires a structured acquisition request")
    budget = approve_additional_acquisition(state["retry_budget"])
    disposition = decide_insufficient_data(
        InsufficientDataContext(
            issues=(
                InsufficientDataIssue(
                    issue_type=reason_code,
                    required=True,
                    resolution_source=ResolutionSource.GOOGLE,
                ),
            ),
            budget_remaining=1 if budget["decision"] == BudgetDecision.ALLOW.value else 0,
            read_only=state.get("requested_effect_type") == "READ",
            evidence_supported_partial_possible=has_supported_evidence(current_update),
            write_required_data_missing=state.get("requested_effect_type") != "READ",
        )
    )
    if disposition is InsufficientDataDisposition.PARTIAL:
        return finalize_supervisor_result(
            state=state,
            intent=FinalizeIntent.COMPLETED.value,
            reason_code="EVIDENCE_SUPPORTED_PARTIAL",
            result_kind="PARTIAL",
            budget_decision=budget,
            current_update=current_update,
        )
    if budget["decision"] == BudgetDecision.DENY.value:
        return finalize_supervisor_result(
            state=state,
            intent=FinalizeIntent.BLOCKED.value,
            reason_code=budget_reason_code(budget, default=reason_code),
            budget_decision=budget,
            current_update=current_update,
        )
    reason_codes = list(request["reason_codes"]) or [reason_code]
    tool_route_plan = state.get("tool_route_plan")
    has_frozen_input_route = bool(
        tool_route_plan is not None and tool_route_plan["input_plan"]["input_routes"]
    )
    if not has_frozen_input_route:
        guard_reason_codes = ["RETRIEVAL_INPUT_ROUTE_UNAVAILABLE", *reason_codes]
        route_signal: RouteReconsiderationRequiredV1 = {
            "kind": "ROUTE_RECONSIDERATION_REQUIRED",
            "reason_codes": guard_reason_codes,
        }
        return make_supervisor_decision(
            target=SupervisorTarget.TOOL_ROUTE,
            next_phase=WorkflowPhase.TOOL_ROUTING,
            state_update=base_supervisor_state_update(
                WorkflowPhase.TOOL_ROUTING,
                retry_budget=budget["run_budget"],
                current_update=current_update,
                workflow_signal=route_signal,
            ),
            reason_code=guard_reason_codes[0],
            budget_decision=budget,
        )
    needs: list[RetrievalNeedV1] = [
        {"required_information": info, "reason_codes": reason_codes}
        for info in request["missing_information"]
    ] or [{"required_information": reason_code, "reason_codes": reason_codes}]
    retrieval_signal: RetrievalRequiredV1 = {
        "kind": "RETRIEVAL_REQUIRED",
        "reason_codes": reason_codes,
        "needs": needs,
    }
    return make_supervisor_decision(
        target=SupervisorTarget.CONTEXT_RETRIEVAL,
        next_phase=WorkflowPhase.CONTEXT_RETRIEVAL,
        state_update=base_supervisor_state_update(
            WorkflowPhase.CONTEXT_RETRIEVAL,
            retry_budget=budget["run_budget"],
            current_update=current_update,
            workflow_signal=retrieval_signal,
        ),
        reason_code=reason_codes[0],
        budget_decision=budget,
    )


__all__ = ["route_retrieval", "route_retrieval_required"]
