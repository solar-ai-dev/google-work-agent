"""Canonical DOMAIN_RECONCILE control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState
from google_work_agent.adapters.langgraph.main.supervisor_decision import (
    SupervisorDecisionV1,
    SupervisorTarget,
    make_supervisor_decision,
)
from google_work_agent.adapters.langgraph.main.supervisor_lifecycle_rules import (
    route_durable_supervisor,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


def domain_reconcile_node(
    state: Mapping[str, object],
    *,
    read_durable_facts: Callable[[str], SupervisorObservationV1],
    project_decision: Callable[
        [Mapping[str, object], Mapping[str, object], SupervisorDecisionV1],
        Mapping[str, object],
    ],
) -> dict[str, object]:
    """Route only from current durable status and its allowed commands."""

    run_id = state.get("run_id")
    if not isinstance(run_id, str) or not run_id:
        raise ValueError("run_id is required")
    try:
        facts = read_durable_facts(run_id)
    except LookupError:
        return _suspend_patch("DOMAIN_FACTS_MISSING")
    decision = route_durable_supervisor(
        state=cast(GraphState, state),
        facts=facts,
    )
    if decision is None:
        decision = make_supervisor_decision(
            target=SupervisorTarget.SUSPEND,
            next_phase=None,
            state_update={},
            reason_code="IN_FLIGHT",
        )
    projected = project_decision(
        state,
        {
            "__workflow_control__": {
                "schema_version": 1,
                "stage": "DOMAIN_RECONCILE",
                "reason": decision["reason_code"],
                "run_status": facts.run_status,
            }
        },
        decision,
    )
    return {key: value for key, value in projected.items() if state.get(key) != value}


def _suspend_patch(reason: str) -> dict[str, object]:
    return {
        "__logical_target__": "end",
        "__target__": "end",
        "__workflow_control__": {
            "schema_version": 1,
            "stage": "DOMAIN_RECONCILE_SUSPENDED",
            "result": "DOMAIN_RECONCILE_SUSPENDED",
            "reason_code": reason,
        },
    }


__all__ = ["domain_reconcile_node"]
