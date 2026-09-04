"""Supervisor no-progress guard and trace projection."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    artifact_revision_projection,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    recovery_supervisor_decision,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


def guard_supervisor_no_progress(
    *,
    state: GraphState,
    decision: SupervisorDecisionV1,
) -> SupervisorDecisionV1:
    """Fail closed when a bounded back-edge repeats without a new revision."""

    if decision["target"] not in {
        SupervisorTarget.TOOL_ROUTE.value,
        SupervisorTarget.CONTEXT_RETRIEVAL.value,
        SupervisorTarget.PLANNING_REVISE_ANSWER.value,
        SupervisorTarget.PLANNING_REVISE_PLAN.value,
        SupervisorTarget.PLAN_REVIEW_RECHECK.value,
    }:
        return decision
    signature = supervisor_progress_signature(state=state, decision=decision)
    trace = state.get("trace_context", {})
    history = trace.get("supervisor_decisions", []) if isinstance(trace, Mapping) else []
    if isinstance(history, list) and any(
        isinstance(item, Mapping)
        and item.get("transition_kind") == "BACK_EDGE"
        and item.get("progress_signature") == signature
        for item in history
    ):
        return recovery_supervisor_decision("SUPERVISOR_NO_PROGRESS")
    return decision


def append_supervisor_trace(
    *,
    trace_context: Mapping[str, object],
    state: GraphState,
    source_phase: str,
    decision: SupervisorDecisionV1,
    durable_facts: SupervisorObservationV1,
    invalidated_fields: list[str],
) -> tuple[dict[str, object], str]:
    projected = dict(trace_context)
    decisions = list(cast(list[dict[str, object]], projected.get("supervisor_decisions", [])))
    transition_kind = supervisor_transition_kind(
        source_phase=source_phase,
        decision=decision,
    )
    decisions.append(
        {
            "source_phase": source_phase,
            "target": decision["target"],
            "next_phase": decision["next_phase"],
            "reason_code": decision["reason_code"],
            "transition_kind": transition_kind,
            "progress_signature": supervisor_progress_signature(
                state=state,
                decision=decision,
            ),
            "invalidated_fields": invalidated_fields,
            "durable_run_status": durable_facts.run_status,
        }
    )
    projected["supervisor_decisions"] = decisions
    return projected, transition_kind


def supervisor_progress_signature(
    *,
    state: GraphState,
    decision: SupervisorDecisionV1,
) -> str:
    revisions = artifact_revision_projection(state)
    ordered = ",".join(f"{key}={revisions[key]}" for key in sorted(revisions))
    return (
        f"{state.get('workflow_phase')}|{decision['target']}|"
        f"{decision.get('reason_code')}|{ordered}"
    )


def supervisor_transition_kind(
    *,
    source_phase: str,
    decision: SupervisorDecisionV1,
) -> str:
    target = decision["target"]
    if target in {
        SupervisorTarget.FINALIZE.value,
        SupervisorTarget.RESPONSE_SYNTHESIS.value,
    }:
        return "TERMINAL"
    if target in {
        SupervisorTarget.WAITING_APPROVAL.value,
        SupervisorTarget.WAITING_CONFIRMATION.value,
        SupervisorTarget.SUSPEND.value,
        SupervisorTarget.REAUTH.value,
        SupervisorTarget.RECOVERY.value,
        SupervisorTarget.CANCEL_RESOLUTION.value,
    }:
        return "SUSPEND"
    rank = {
        WorkflowPhase.REQUEST_ANALYSIS.value: 1,
        WorkflowPhase.TOOL_ROUTING.value: 2,
        WorkflowPhase.CONTEXT_RETRIEVAL.value: 3,
        WorkflowPhase.WORK_ANALYSIS.value: 4,
        WorkflowPhase.SOLUTION_PLANNING.value: 5,
        WorkflowPhase.PLAN_REVIEW.value: 6,
        WorkflowPhase.DOMAIN_VALIDATION.value: 7,
        WorkflowPhase.WAITING_APPROVAL.value: 8,
        WorkflowPhase.PREFLIGHT.value: 9,
        WorkflowPhase.ACTION_EXECUTION.value: 10,
        WorkflowPhase.VERIFICATION.value: 11,
    }
    next_phase = decision.get("next_phase")
    if isinstance(next_phase, str) and rank.get(next_phase, 99) <= rank.get(source_phase, 0):
        return "BACK_EDGE"
    if decision.get("reason_code") in {
        "RETRIEVAL_AND_WORK_ANALYSIS_NOT_REQUIRED",
        "WORK_ANALYSIS_NOT_REQUIRED",
        "RETRIEVAL_NOT_REQUIRED",
    }:
        return "SKIP"
    return "FORWARD"


__all__ = [
    "append_supervisor_trace",
    "guard_supervisor_no_progress",
    "supervisor_progress_signature",
    "supervisor_transition_kind",
]
