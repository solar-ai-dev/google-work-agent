"""Thin adapter for planning.draft_action_objective_per_output_route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
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
    projected = project_planning_input(state)
    tool_route_plan = projected.get("tool_route_plan")
    request_intent = projected.get("request_intent")
    user_request = projected.get("user_request")
    work_analysis = projected.get("work_analysis_result")
    evidence = projected.get("evidence", ())
    if not isinstance(tool_route_plan, Mapping) or not isinstance(request_intent, Mapping):
        raise ValueError("tool_route_plan and request_intent are required")
    if not isinstance(user_request, str):
        raise ValueError("user_request is required")
    if work_analysis is not None and not isinstance(work_analysis, Mapping):
        raise ValueError("work_analysis_result must be an object")
    if not isinstance(evidence, Sequence) or isinstance(evidence, (str, bytes)):
        raise ValueError("evidence must be a sequence")
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping):
        raise ValueError("tool_route_plan.output_plan is required")
    output_routes = output_plan.get("output_routes")
    if not isinstance(output_routes, Sequence) or isinstance(output_routes, (str, bytes)):
        raise ValueError("tool_route_plan.output_plan.output_routes is required")
    return {
        "action_objectives": draft_action_objective_per_output_route(
            output_routes,  # type: ignore[arg-type]
            user_request=user_request,
            request_intent=request_intent,
            work_analysis=work_analysis,
            evidence=evidence,  # type: ignore[arg-type]
            invoke=invoke,
        )
    }
