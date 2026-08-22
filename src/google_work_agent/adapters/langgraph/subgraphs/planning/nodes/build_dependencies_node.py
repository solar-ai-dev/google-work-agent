"""Thin LangGraph adapter for planning.build_dependencies."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import project_planning_input

def build_dependencies_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_planning_input(state)
    return {"dependencies": operation(projected)}
