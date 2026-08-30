"""Thin adapter for planning.compose_answer."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    compose_answer_projection,
)
from google_work_agent.application.agents.planning.compose_answer import compose_answer
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)


def compose_answer_node(
    state: Mapping[str, object], *, invoke: PlanningSemanticInvoker
) -> dict[str, object]:
    projected = compose_answer_projection.project_compose_answer_input(state)
    return {
        "answer_draft": compose_answer(
            user_request=projected["user_request"],  # type: ignore[arg-type]
            request_intent=projected["request_intent"],  # type: ignore[arg-type]
            answer_outline=projected["answer_outline"],  # type: ignore[arg-type]
            work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
            evidence=projected["evidence"],  # type: ignore[arg-type]
            invoke=invoke,
            confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
        )
    }
