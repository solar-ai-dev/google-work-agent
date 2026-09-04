"""Canonical INITIALIZE control node."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from google_work_agent.adapters.langgraph.main.state import GraphState, WorkflowPhase
from google_work_agent.adapters.langgraph.main.supervisor import route_supervisor
from google_work_agent.adapters.langgraph.main.supervisor_decision import SupervisorDecisionV1
from google_work_agent.application.use_cases.run.start_analysis import StartAnalysisResult


def initialize_node(
    state: Mapping[str, object],
    *,
    start_analysis: Callable[[str], StartAnalysisResult],
    project_decision: Callable[
        [Mapping[str, object], Mapping[str, object], SupervisorDecisionV1],
        Mapping[str, object],
    ],
) -> dict[str, object]:
    """Apply ``run.start_analysis`` and project only Main control fields."""

    run_id = _required_string(state.get("run_id"), "run_id")
    result = start_analysis(run_id)
    decision = route_supervisor(
        phase=WorkflowPhase.INITIALIZE,
        state=cast(GraphState, state),
        result={"current_status": result.current_status},
    )
    projected = project_decision(state, {}, decision)
    return {key: value for key, value in projected.items() if state.get(key) != value}


def _required_string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


__all__ = ["initialize_node"]
