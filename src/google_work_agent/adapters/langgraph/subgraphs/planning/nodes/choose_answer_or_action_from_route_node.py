"""Thin adapter for planning.choose_answer_or_action_from_route."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.choose_answer_or_action_from_route import (
    choose_answer_or_action_from_route,
)


def choose_answer_or_action_from_route_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_planning_input(state)
    tool_route_plan = projected.get("tool_route_plan")
    if not isinstance(tool_route_plan, Mapping):
        raise ValueError("tool_route_plan is required")
    return {"planning_disposition": choose_answer_or_action_from_route(tool_route_plan)}
