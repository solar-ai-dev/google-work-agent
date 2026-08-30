"""Thin adapter for planning.draft_action_objective_per_output_route."""

from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    draft_action_objective_per_output_route_projection as objective_projection,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.draft_action_objective_per_output_route import (
    draft_action_objective_per_output_route,
)


def draft_action_objective_per_output_route_node(
    state: Mapping[str, object], *, invoke: PlanningSemanticInvoker
) -> dict[str, object]:
    projected = objective_projection.project_draft_action_objective_per_output_route_input(state)
    return {
        "action_objective_candidates": list(
            draft_action_objective_per_output_route(
                projected["output_routes"],  # type: ignore[arg-type]
                user_request=projected["user_request"],  # type: ignore[arg-type]
                request_intent=projected["request_intent"],  # type: ignore[arg-type]
                work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
                evidence=projected["evidence"],  # type: ignore[arg-type]
                invoke=invoke,
            )
        )
    }
