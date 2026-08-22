"""Compose business arguments per frozen output route without route reselection."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    PlanningSemanticInvoker,
    ToolArgumentCandidateV1,
)

PROMPT_ID = "planning.compose_arguments_per_output_route"
LegacyWriter = Callable[[Mapping[str, object]], ToolArgumentCandidateV1]


def compose_arguments_per_output_route(
    output_routes: Sequence[Mapping[str, object]],
    *,
    objectives: Sequence[ActionObjectiveCandidateV1] = (),
    user_request: str = "",
    work_analysis: Mapping[str, object] | None = None,
    evidence: Sequence[Mapping[str, object]] = (),
    invoke: PlanningSemanticInvoker | None = None,
    writer: LegacyWriter | None = None,
) -> tuple[ToolArgumentCandidateV1, ...]:
    """Use canonical objective-aware Prompt input; retain writer= only as an import bridge."""
    if not output_routes:
        raise ValueError("ACTION planning requires at least one output route")
    if invoke is None and writer is None:
        raise ValueError("canonical invoke or compatibility writer is required")
    objective_by_route = {item["route_id"]: item for item in objectives}
    if len(objective_by_route) != len(objectives):
        raise ValueError("duplicate objective route")
    candidates: list[ToolArgumentCandidateV1] = []
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        if invoke is None:
            assert writer is not None
            candidate: Mapping[str, object] = writer(route)
        else:
            objective = objective_by_route.get(route_id)
            if objective is None:
                raise ValueError("every canonical output route requires an objective")
            candidate = invoke(
                PROMPT_ID,
                {
                    "user_request": user_request,
                    "output_route": dict(route),
                    "action_objective": dict(objective),
                    "work_analysis": dict(work_analysis) if work_analysis is not None else None,
                    "evidence": [dict(item) for item in evidence],
                },
            )
        if candidate.get("route_id") != route_id:
            raise ValueError("argument candidate escaped its frozen output route")
        arguments = candidate.get("arguments")
        refs = candidate.get("evidence_refs", [])
        if not isinstance(arguments, dict):
            raise ValueError("argument candidate requires business arguments")
        forbidden = {"tool_id", "tool_name", "effect", "approval", "dependencies", "execution", "verification"}
        if invoke is not None and forbidden.intersection(arguments):
            raise ValueError("argument candidate attempted to author deterministic authority")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("argument candidate evidence_refs must be strings")
        candidates.append(
            {"schema_version": int(candidate.get("schema_version", 1)), "route_id": route_id,
             "arguments": dict(arguments), "evidence_refs": list(refs)}
        )
    return tuple(candidates)
