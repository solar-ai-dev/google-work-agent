"""Deterministic approval and execution-boundary Supervisor rules."""

from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    base_supervisor_state_update,
    boundary_supervisor_state_update,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_terminal_projection import (
    JsonObject,
    domain_validation_reason_code,
    finalize_supervisor_result,
    preflight_result_code,
    preflight_safe_error_code,
)
from google_work_agent.application.agents.planning.contracts.domain_validation import (
    DomainValidationOutputV1,
    DomainValidationResult,
)
from google_work_agent.application.use_cases.run.terminal_contract import FinalizeIntent


def route_domain_validation(
    *,
    state: GraphState,
    result: DomainValidationOutputV1,
) -> SupervisorDecisionV1:
    validation_result = DomainValidationResult(str(result["result"]))
    if validation_result is DomainValidationResult.REQUIRE_APPROVAL:
        return make_supervisor_decision(
            target=SupervisorTarget.WAITING_APPROVAL,
            next_phase=WorkflowPhase.WAITING_APPROVAL,
            state_update=base_supervisor_state_update(WorkflowPhase.WAITING_APPROVAL),
            reason_code=domain_validation_reason_code(result, default="REQUIRE_APPROVAL"),
        )
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=domain_validation_reason_code(result, default="DOMAIN_VALIDATION_BLOCKED"),
        planning_result=state.get("planning_result"),
        plan_review=state.get("plan_review"),
        work_analysis_result=state.get("work_analysis_result"),
    )


def route_preflight(
    *,
    state: GraphState,
    result: JsonObject,
) -> SupervisorDecisionV1:
    result_code = preflight_result_code(result, default="PREFLIGHT_REJECTED")
    safe_error_code = preflight_safe_error_code(result)
    raw_target = result.get("__logical_target__", result.get("__target__"))
    if safe_error_code == "REAUTH_REQUIRED" or result_code == "REAUTH_REQUIRED":
        return make_supervisor_decision(
            target=SupervisorTarget.REAUTH,
            next_phase=None,
            state_update=boundary_supervisor_state_update(),
            reason_code="REAUTH_REQUIRED",
        )
    if bool(result.get("applied")) or raw_target == "action_execution":
        return make_supervisor_decision(
            target=SupervisorTarget.ACTION_EXECUTION,
            next_phase=WorkflowPhase.ACTION_EXECUTION,
            state_update=base_supervisor_state_update(WorkflowPhase.ACTION_EXECUTION),
            reason_code=result_code,
        )
    target = {
        "domain_reconcile": SupervisorTarget.DOMAIN_RECONCILE,
        "recovery": SupervisorTarget.RECOVERY,
        "response_synthesis": SupervisorTarget.RESPONSE_SYNTHESIS,
        "waiting_approval": SupervisorTarget.WAITING_APPROVAL,
    }.get(str(raw_target))
    if target is not None:
        return make_supervisor_decision(
            target=target,
            next_phase=None,
            state_update=boundary_supervisor_state_update(),
            reason_code=result_code,
        )
    if raw_target == "end":
        return make_supervisor_decision(
            target=SupervisorTarget.SUSPEND,
            next_phase=None,
            state_update=boundary_supervisor_state_update(),
            reason_code=result_code,
        )
    return finalize_supervisor_result(
        state=state,
        intent=FinalizeIntent.BLOCKED.value,
        reason_code=result_code,
    )


__all__ = ["route_domain_validation", "route_preflight"]
