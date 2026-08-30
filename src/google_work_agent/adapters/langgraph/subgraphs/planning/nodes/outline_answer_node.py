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
        user_request=projected["user_request"],  # type: ignore[arg-type]
        request_intent=projected["request_intent"],  # type: ignore[arg-type]
        work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
        evidence=projected["evidence"],  # type: ignore[arg-type]
        invoke=invoke,
        confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
    )
    if result.get("disposition") == "NEEDS_CONFIRMATION":
        return {"planning_confirmation": result}
    return {"answer_outline": result}
