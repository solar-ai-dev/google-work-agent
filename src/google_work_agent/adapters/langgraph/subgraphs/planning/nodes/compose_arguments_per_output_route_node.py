"""Thin LangGraph adapter for planning.compose_arguments_per_output_route."""

from __future__ import annotations
from collections.abc import Callable, Mapping
from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import project_planning_input

def compose_arguments_per_output_route_node(state: Mapping[str, object], *, operation: Callable[[object], object]) -> dict[str, object]:
    projected = project_planning_input(state)
    return {"argument_candidates": operation(projected)}
