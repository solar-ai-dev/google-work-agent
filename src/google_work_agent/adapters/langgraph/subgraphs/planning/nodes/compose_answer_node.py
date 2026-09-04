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
            user_request=projected["user_request"],
            request_intent=projected["request_intent"],
            answer_outline=projected["answer_outline"],
            work_analysis=projected.get("work_analysis"),
            evidence=projected["evidence"],
            invoke=invoke,
            confirmation_response=projected.get("confirmation_response"),
            retrieval_result=projected.get("retrieval_result"),
        )
    }
