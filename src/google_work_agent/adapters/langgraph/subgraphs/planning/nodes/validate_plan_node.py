"""Thin adapter for deterministic planning.validate_plan."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.validate_plan import validate_plan


def validate_plan_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_planning_input(state)
    plan_draft = projected.get("plan_draft")
    if plan_draft is None:
        raise ValueError("plan_draft is required")
    return {"validated_plan": validate_plan(plan_draft)}
