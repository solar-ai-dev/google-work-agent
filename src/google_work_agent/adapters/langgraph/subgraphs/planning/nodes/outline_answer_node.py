"""Thin adapter for planning.outline_answer."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    outline_answer_projection,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.outline_answer import outline_answer


def outline_answer_node(
    state: Mapping[str, object], *, invoke: PlanningSemanticInvoker
) -> dict[str, object]:
    projected = outline_answer_projection.project_outline_answer_input(state)
    result = outline_answer(
        user_request=projected["user_request"],
        request_intent=projected["request_intent"],
        work_analysis=projected.get("work_analysis"),
        evidence=projected["evidence"],
        invoke=invoke,
        confirmation_response=projected.get("confirmation_response"),
    )
    if result.get("disposition") == "NEEDS_CONFIRMATION":
        return {"planning_confirmation": result}
    return {"answer_outline": result}
