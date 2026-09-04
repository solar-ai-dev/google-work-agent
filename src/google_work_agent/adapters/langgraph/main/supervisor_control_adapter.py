"""Translate legacy lifecycle control output into one Supervisor candidate."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.main.state import WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    make_supervisor_decision,
)

_TARGETS = {
    "action_execution": SupervisorTarget.ACTION_EXECUTION,
    "cancel_resolution": SupervisorTarget.CANCEL_RESOLUTION,
    "domain_reconcile": SupervisorTarget.DOMAIN_RECONCILE,
    "end": SupervisorTarget.SUSPEND,
    "preflight": SupervisorTarget.PREFLIGHT,
    "review_entry": SupervisorTarget.PLAN_REVIEW_INSPECT,
    "recovery": SupervisorTarget.RECOVERY,
    "response_synthesis": SupervisorTarget.RESPONSE_SYNTHESIS,
    "verification": SupervisorTarget.VERIFICATION,
    "waiting_approval": SupervisorTarget.WAITING_APPROVAL,
}


def lifecycle_control_decision(
    *,
    source_phase: WorkflowPhase,
    control_result: Mapping[str, object],
) -> SupervisorDecisionV1:
    """Adapt an existing lifecycle disposition; Supervisor remains final authority."""

    raw_target = control_result.get("__logical_target__", control_result.get("__target__"))
    target: SupervisorTarget | None
    if raw_target == "end" and _control_reason(control_result) == "REAUTH_REQUIRED":
        target = SupervisorTarget.REAUTH
    else:
        target = _TARGETS.get(str(raw_target))
    if target is None:
        raise ValueError(
            f"{source_phase.value} lifecycle result returned an unregistered target: "
            f"{raw_target!r}"
        )
    next_phase = _next_phase(control_result)
    return make_supervisor_decision(
        target=target,
        next_phase=next_phase,
        state_update={},
        reason_code=_control_reason(control_result),
    )


def lifecycle_state_update(control_result: Mapping[str, object]) -> dict[str, object]:
    """Remove the legacy routing fields while retaining owner-produced facts."""

    return {
        key: value
        for key, value in control_result.items()
        if key not in {"__target__", "__logical_target__"}
    }


def _control_reason(control_result: Mapping[str, object]) -> str:
    control = control_result.get("__workflow_control__")
    if isinstance(control, Mapping):
        reason = control.get("reason", control.get("stage"))
        if isinstance(reason, str) and reason:
            return reason
    target = control_result.get("__logical_target__", control_result.get("__target__"))
    return f"{str(target or 'UNKNOWN').upper()}_REQUIRED"


def _next_phase(control_result: Mapping[str, object]) -> WorkflowPhase | None:
    value = control_result.get("workflow_phase")
    if not isinstance(value, str):
        return None
    try:
        return WorkflowPhase(value)
    except ValueError:
        return None


__all__ = ["lifecycle_control_decision", "lifecycle_state_update"]
