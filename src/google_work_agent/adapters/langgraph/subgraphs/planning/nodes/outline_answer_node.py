"""Thin LangGraph adapter for planning.outline_answer."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import project_planning_input

def outline_answer_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_planning_input(state)
    return {"answer_outline": operation(projected)}
