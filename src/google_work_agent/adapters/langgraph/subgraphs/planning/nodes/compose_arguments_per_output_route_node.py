"""Thin adapter for planning.compose_arguments_per_output_route."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.planning.projections import (
    compose_arguments_per_output_route_projection as arguments_projection,
)
from google_work_agent.application.agents.planning.compose_arguments_per_output_route import (
    compose_arguments_per_output_route,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.planning.contracts.planning_tool_schema import (
    planning_tool_argument_schema,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    resolve_default_container,
)


def compose_arguments_per_output_route_node(
    state: Mapping[str, object],
    *,
    invoke: PlanningSemanticInvoker,
    default_tasklist_id_provider: Callable[[], str | None] | None = None,
    default_calendar_id_provider: Callable[[], str | None] | None = None,
) -> dict[str, object]:
    projected = arguments_projection.project_compose_arguments_per_output_route_input(state)
    routes = cast(list[dict[str, object]], projected["output_routes"])
    confirmation = projected.get("confirmation_response")
    explicit_container_id: str | None = None
    if isinstance(confirmation, Mapping):
        candidate = confirmation.get("selected_option") or confirmation.get("free_text")
        explicit_container_id = candidate if isinstance(candidate, str) and candidate else None
    missing = state.get("prompt_context")
    missing_route_id: str | None = None
    if isinstance(missing, Mapping) and isinstance(
        missing.get("planning_missing_container"), Mapping
    ):
        raw_route_id = missing["planning_missing_container"].get("route_id")
        missing_route_id = raw_route_id if isinstance(raw_route_id, str) else None
    bound_schemas = [
        resolve_default_container(
            route=route,  # type: ignore[arg-type]
            selected_tool_schema=planning_tool_argument_schema(
                cast(str, route["selected_tool_id"])
            ),
            explicit_container_id=(
                explicit_container_id if route.get("route_id") == missing_route_id else None
            ),
            default_tasklist_id_provider=default_tasklist_id_provider,
            default_calendar_id_provider=default_calendar_id_provider,
        )
        for route in routes
    ]
    return {
        "argument_candidates": list(
            compose_arguments_per_output_route(
                routes,
                objectives=projected["objectives"],  # type: ignore[arg-type]
                bound_tool_schemas=bound_schemas,
                work_analysis=projected.get("work_analysis"),  # type: ignore[arg-type]
                evidence=projected["evidence"],  # type: ignore[arg-type]
                invoke=invoke,
                confirmation_response=projected.get("confirmation_response"),  # type: ignore[arg-type]
            )
        )
    }
