"""Typed Supervisor decision contract and GraphState update projection."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TypedDict, cast

from google_work_agent.adapters.langgraph.main.state import GraphStateUpdateV1, WorkflowPhase
from google_work_agent.application.use_cases.run.guard_run_budget import BudgetDecisionV1

JsonObject = dict[str, object]


class SupervisorTarget(StrEnum):
    """Registered logical destinations selected by deterministic rules."""

    REQUEST_UNDERSTANDING = "REQUEST_UNDERSTANDING"
    DOMAIN_RECONCILE = "DOMAIN_RECONCILE"
    TOOL_ROUTE = "TOOL_ROUTE"
    CONTEXT_RETRIEVAL = "CONTEXT_RETRIEVAL"
    WORK_ANALYSIS = "WORK_ANALYSIS"
    SOLUTION_PLANNING = "SOLUTION_PLANNING"
    PLAN_REVIEW_INSPECT = "PLAN_REVIEW_INSPECT"
    PLAN_REVIEW_RECHECK = "PLAN_REVIEW_RECHECK"
    PLANNING_REVISE_ANSWER = "PLANNING_REVISE_ANSWER"
    PLANNING_REVISE_PLAN = "PLANNING_REVISE_PLAN"
    DOMAIN_VALIDATION = "DOMAIN_VALIDATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    PREFLIGHT = "PREFLIGHT"
    ACTION_EXECUTION = "ACTION_EXECUTION"
    VERIFICATION = "VERIFICATION"
    CANCEL_RESOLUTION = "CANCEL_RESOLUTION"
    WAITING_CONFIRMATION = "WAITING_CONFIRMATION"
    RESPONSE_SYNTHESIS = "RESPONSE_SYNTHESIS"
    FINALIZE = "FINALIZE"
    SUSPEND = "SUSPEND"
    REAUTH = "REAUTH"
    RECOVERY = "RECOVERY"


class SupervisorDecisionV1(TypedDict):
    """Minimal deterministic routing result returned by the Supervisor."""

    target: str
    next_phase: str | None
    state_update: GraphStateUpdateV1
    reason_code: str | None
    budget_decision: BudgetDecisionV1 | None


def make_supervisor_decision(
    *,
    target: SupervisorTarget,
    next_phase: WorkflowPhase | None,
    state_update: Mapping[str, object],
    reason_code: str | None = None,
    budget_decision: BudgetDecisionV1 | None = None,
) -> SupervisorDecisionV1:
    return {
        "target": target.value,
        "next_phase": None if next_phase is None else next_phase.value,
        "state_update": validate_supervisor_state_update(state_update),
        "reason_code": reason_code,
        "budget_decision": budget_decision,
    }


def base_supervisor_state_update(
    next_phase: WorkflowPhase,
    *,
    retry_budget: object | None = None,
    current_update: Mapping[str, object] | None = None,
    **extra: object,
) -> JsonObject:
    update: JsonObject = {
        "workflow_phase": next_phase.value,
        "user_interrupt": None,
        "finalize_intent": None,
    }
    if retry_budget is not None:
        update["retry_budget"] = retry_budget
    if current_update is not None:
        update.update(current_update)
    update.update(extra)
    return update


def boundary_supervisor_state_update(**extra: object) -> JsonObject:
    update: JsonObject = {
        "user_interrupt": None,
        "finalize_intent": None,
    }
    update.update(extra)
    return update


def recovery_supervisor_decision(reason_code: str) -> SupervisorDecisionV1:
    return make_supervisor_decision(
        target=SupervisorTarget.RECOVERY,
        next_phase=WorkflowPhase.RECOVERY,
        state_update=base_supervisor_state_update(WorkflowPhase.RECOVERY),
        reason_code=reason_code,
    )


def validate_supervisor_state_update(value: Mapping[str, object]) -> GraphStateUpdateV1:
    unknown_fields = set(value).difference(GraphStateUpdateV1.__annotations__)
    if unknown_fields:
        names = ", ".join(sorted(unknown_fields))
        raise ValueError(f"supervisor state update contains unknown fields: {names}")
    return cast(GraphStateUpdateV1, dict(value))


__all__ = [
    "SupervisorDecisionV1",
    "SupervisorTarget",
    "base_supervisor_state_update",
    "boundary_supervisor_state_update",
    "make_supervisor_decision",
    "recovery_supervisor_decision",
    "validate_supervisor_state_update",
]
