"""Apply one deterministic Supervisor decision to Main GraphState."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.adapters.langgraph.main.state import (
    GraphState,
    GraphStateUpdateV1,
    WorkflowPhase,
)
from google_work_agent.adapters.langgraph.main.supervisor_artifact_revisions import (
    invalidate_stale_downstream,
)
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.adapters.langgraph.main.supervisor_lifecycle_rules import (
    apply_durable_priority,
)
from google_work_agent.adapters.langgraph.main.supervisor_progress import (
    append_supervisor_trace,
    guard_supervisor_no_progress,
)
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    SupervisorObservationV1,
)


@dataclass(frozen=True, slots=True)
class SupervisorStateProjectionV1:
    state: GraphState
    decision: SupervisorDecisionV1
    source_phase: str
    transition_kind: str
    invalidated_fields: tuple[str, ...]


def project_supervisor_state(
    *,
    state: GraphState,
    stage_update: GraphStateUpdateV1,
    candidate: SupervisorDecisionV1,
    durable_facts: SupervisorObservationV1,
) -> SupervisorStateProjectionV1:
    """Apply guards, durable priority, invalidation, and trace as one projection."""

    source_phase = str(state.get("workflow_phase", WorkflowPhase.INITIALIZE.value))
    decision = apply_durable_priority(state=state, decision=candidate, facts=durable_facts)
    decision = guard_supervisor_no_progress(state=state, decision=decision)
    decision_state = decision["state_update"]
    merged: GraphState = {**state, **stage_update, **decision_state}
    merged["prompt_context"] = {
        **state.get("prompt_context", {}),
        **stage_update.get("prompt_context", {}),
        **decision_state.get("prompt_context", {}),
    }
    merged_trace = {
        **state.get("trace_context", {}),
        **stage_update.get("trace_context", {}),
        **decision_state.get("trace_context", {}),
    }
    invalidated_fields = invalidate_stale_downstream(previous=state, current=merged)
    trace, transition_kind = append_supervisor_trace(
        trace_context=merged_trace,
        state=merged,
        source_phase=source_phase,
        decision=decision,
        durable_facts=durable_facts,
        invalidated_fields=invalidated_fields,
    )
    merged["trace_context"] = trace
    return SupervisorStateProjectionV1(
        state=merged,
        decision=decision,
        source_phase=source_phase,
        transition_kind=transition_kind,
        invalidated_fields=tuple(invalidated_fields),
    )


__all__ = ["SupervisorStateProjectionV1", "project_supervisor_state"]
