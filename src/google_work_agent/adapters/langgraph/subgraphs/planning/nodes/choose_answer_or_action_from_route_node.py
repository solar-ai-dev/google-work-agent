"""Thin LangGraph adapter for planning.choose_answer_or_action_from_route."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import project_planning_input

def choose_answer_or_action_from_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_planning_input(state)
    return {"planning_disposition": operation(projected)}
