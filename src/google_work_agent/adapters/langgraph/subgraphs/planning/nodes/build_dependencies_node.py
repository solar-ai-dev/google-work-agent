"""Thin adapter for deterministic planning.build_dependencies."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.adapters.langgraph.subgraphs.planning.projections.planning_projection import (
    project_planning_input,
)
from google_work_agent.application.agents.planning.build_dependencies import build_dependencies
from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    PlanningActionSeedV1,
)


def build_dependencies_node(state: Mapping[str, object]) -> dict[str, object]:
    projected = project_planning_input(state)
    tool_route_plan = projected.get("tool_route_plan")
    candidates = projected.get("argument_candidates")
    action_ids = projected.get("action_ids_by_route")
    if not isinstance(tool_route_plan, Mapping):
        raise ValueError("tool_route_plan is required")
    if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)):
        raise ValueError("argument_candidates are required")
    if not isinstance(action_ids, Mapping):
        raise ValueError("action_ids_by_route is required")
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping):
        raise ValueError("tool_route_plan.output_plan is required")
    routes = output_plan.get("output_routes")
    if not isinstance(routes, Sequence) or isinstance(routes, (str, bytes)):
        raise ValueError("tool_route_plan.output_plan.output_routes is required")
    candidate_by_route = {
        item.get("route_id"): item
        for item in candidates
        if isinstance(item, Mapping) and isinstance(item.get("route_id"), str)
    }
    seeds: list[PlanningActionSeedV1] = []
    for route in routes:
        if not isinstance(route, Mapping):
            raise ValueError("output route must be an object")
        route_id = route.get("route_id")
        tool_id = route.get("selected_tool_id")
        effect = route.get("effect")
        if (
            not isinstance(route_id, str)
            or not isinstance(tool_id, str)
            or not isinstance(effect, str)
        ):
            raise ValueError("output route identity is incomplete")
        candidate = candidate_by_route.get(route_id)
        action_id = action_ids.get(route_id)
        if not isinstance(candidate, Mapping) or not isinstance(action_id, str):
            raise ValueError("each output route requires one candidate and action id")
        arguments = candidate.get("arguments")
        evidence_refs = candidate.get("evidence_refs")
        if not isinstance(arguments, Mapping) or not isinstance(evidence_refs, list):
            raise ValueError("argument candidate is invalid")
        seeds.append(
            {
                "action_id": action_id,
                "route_id": route_id,
                "tool_id": tool_id,
                "effect": effect,  # type: ignore[typeddict-item]
                "arguments": dict(arguments),
                "evidence_refs": list(evidence_refs),
            }
        )
    return {"action_seeds": tuple(seeds), "dependencies": build_dependencies(seeds)}
