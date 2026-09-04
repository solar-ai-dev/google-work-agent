"""Durable lifecycle preemption rules for deterministic Main routing."""

from __future__ import annotations

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    base_supervisor_state_update,
    boundary_supervisor_state_update,
    make_supervisor_decision,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


def apply_durable_priority(
    *,
    state: GraphState,
    decision: SupervisorDecisionV1,
    facts: SupervisorObservationV1,
) -> SupervisorDecisionV1:
    """Preempt a semantic candidate without applying lifecycle commands or I/O."""

    status = facts.run_status
    action_statuses = frozenset(facts.action_statuses)
    candidate = decision["target"]

    if status in {"COMPLETED", "BLOCKED", "FAILED", "CANCELLED"}:
        if candidate in {
            SupervisorTarget.RESPONSE_SYNTHESIS.value,
            SupervisorTarget.FINALIZE.value,
        }:
            return decision
        return _priority_decision(
            target=SupervisorTarget.RESPONSE_SYNTHESIS,
            phase=WorkflowPhase.RESPONSE_SYNTHESIS,
            reason_code=f"DURABLE_{status}",
        )

    # A lifecycle owner explicitly returns SUSPEND when it cannot make a
    # durable transition in this invocation. Re-entering the same Recovery,
    # Verification, or Cancel node would repeat commands without new facts.
    if candidate == SupervisorTarget.SUSPEND.value:
        return decision

    if status == "CANCEL_REQUESTED" or facts.cancel_intent_active:
        if (
            candidate == SupervisorTarget.RESPONSE_SYNTHESIS.value
            and decision["reason_code"] in {"READY_TO_FINALIZE", "FINALIZED"}
        ):
            # CancelResolution has proved every child settled.  The terminal
            # commit still owns the CANCELLED transition and final message;
            # sending this handoff back to CancelResolution cannot add a fact.
            return decision
        if "UNKNOWN_RESULT" in action_statuses or "MISMATCH" in action_statuses:
            return _priority_decision(
                target=SupervisorTarget.RECOVERY,
                phase=WorkflowPhase.RECOVERY,
                reason_code="CANCEL_UNKNOWN_RESULT_RECOVERY",
            )
        if "EXECUTED" in action_statuses:
            return _priority_decision(
                target=SupervisorTarget.VERIFICATION,
                phase=WorkflowPhase.VERIFICATION,
                reason_code="CANCEL_UNVERIFIED_WRITE",
            )
        if "EXECUTING" in action_statuses:
            return _priority_decision(
                target=SupervisorTarget.ACTION_EXECUTION,
                phase=WorkflowPhase.ACTION_EXECUTION,
                reason_code="CANCEL_IN_FLIGHT_SETTLEMENT",
            )
        return _priority_decision(
            target=SupervisorTarget.CANCEL_RESOLUTION,
            phase=None,
            reason_code="CANCEL_RESOLUTION_REQUIRED",
        )

    if status == "REAUTH_REQUIRED":
        return _priority_decision(
            target=SupervisorTarget.REAUTH,
            phase=None,
            reason_code="REAUTH_REQUIRED",
        )
    if status == "RECOVERY_REQUIRED":
        return _priority_decision(
            target=SupervisorTarget.RECOVERY,
            phase=WorkflowPhase.RECOVERY,
            reason_code="RECOVERY_REQUIRED",
        )
    if "UNKNOWN_RESULT" in action_statuses or "MISMATCH" in action_statuses:
        return _priority_decision(
            target=SupervisorTarget.RECOVERY,
            phase=WorkflowPhase.RECOVERY,
            reason_code="UNKNOWN_OR_MISMATCH_RESULT",
        )
    if "EXECUTED" in action_statuses:
        return _priority_decision(
            target=SupervisorTarget.VERIFICATION,
            phase=WorkflowPhase.VERIFICATION,
            reason_code="UNVERIFIED_WRITE",
        )
    if "EXECUTING" in action_statuses:
        return _priority_decision(
            target=SupervisorTarget.ACTION_EXECUTION,
            phase=WorkflowPhase.ACTION_EXECUTION,
            reason_code="EXECUTION_IN_FLIGHT",
        )
    if status == "WAITING_CONFIRMATION" and candidate != SupervisorTarget.WAITING_CONFIRMATION:
        return _priority_decision(
            target=SupervisorTarget.WAITING_CONFIRMATION,
            phase=WorkflowPhase.WAITING_CONFIRMATION,
            reason_code="WAITING_CONFIRMATION",
        )
    if status == "WAITING_APPROVAL" and candidate not in {
        SupervisorTarget.WAITING_APPROVAL.value,
        SupervisorTarget.DOMAIN_VALIDATION.value,
        SupervisorTarget.PREFLIGHT.value,
        SupervisorTarget.VERIFICATION.value,
    }:
        return _priority_decision(
            target=SupervisorTarget.WAITING_APPROVAL,
            phase=WorkflowPhase.WAITING_APPROVAL,
            reason_code="WAITING_APPROVAL",
        )
    if status == "VERIFYING" and candidate not in {
        SupervisorTarget.VERIFICATION.value,
        SupervisorTarget.RECOVERY.value,
        SupervisorTarget.CANCEL_RESOLUTION.value,
        SupervisorTarget.RESPONSE_SYNTHESIS.value,
        SupervisorTarget.FINALIZE.value,
    }:
        return _priority_decision(
            target=SupervisorTarget.VERIFICATION,
            phase=WorkflowPhase.VERIFICATION,
            reason_code="VERIFICATION_REQUIRED",
        )
    if status == "EXECUTING" and candidate not in {
        SupervisorTarget.ACTION_EXECUTION.value,
        SupervisorTarget.RECOVERY.value,
        SupervisorTarget.REAUTH.value,
        SupervisorTarget.CANCEL_RESOLUTION.value,
    }:
        return _priority_decision(
            target=SupervisorTarget.ACTION_EXECUTION,
            phase=WorkflowPhase.ACTION_EXECUTION,
            reason_code="EXECUTION_IN_FLIGHT",
        )
    return decision


def route_durable_supervisor(
    *,
    state: GraphState,
    facts: SupervisorObservationV1,
) -> SupervisorDecisionV1 | None:
    """Return a durable preemption route, or no decision when semantics may proceed."""

    candidate = make_supervisor_decision(
        target=SupervisorTarget.REQUEST_UNDERSTANDING,
        next_phase=None,
        state_update={},
        reason_code="DOMAIN_RECONCILE",
    )
    routed = apply_durable_priority(state=state, decision=candidate, facts=facts)
    return None if routed is candidate else routed


def _priority_decision(
    *,
    target: SupervisorTarget,
    phase: WorkflowPhase | None,
    reason_code: str,
) -> SupervisorDecisionV1:
    update = (
        boundary_supervisor_state_update()
        if phase is None
        else base_supervisor_state_update(phase)
    )
    return make_supervisor_decision(
        target=target,
        next_phase=phase,
        state_update=update,
        reason_code=reason_code,
    )


__all__ = [
    "apply_durable_priority",
    "route_durable_supervisor",
]
