"""Draft one bounded business objective for each frozen output route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    PlanningSemanticInvoker,
)

PROMPT_ID = "planning.draft_action_objective_per_output_route"


def draft_action_objective_per_output_route(
    output_routes: Sequence[Mapping[str, object]],
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    evidence: Sequence[Mapping[str, object]],
    invoke: PlanningSemanticInvoker,
) -> tuple[ActionObjectiveCandidateV1, ...]:
    if not output_routes:
        raise ValueError("ACTION planning requires at least one output route")
    result: list[ActionObjectiveCandidateV1] = []
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        candidate = invoke(
            PROMPT_ID,
            {
                "user_request": user_request,
                "request_intent": dict(request_intent),
                "output_route": dict(route),
                "work_analysis": dict(work_analysis) if work_analysis is not None else None,
                "evidence": [dict(item) for item in evidence],
            },
        )
        objective = candidate.get("objective")
        refs = candidate.get("evidence_refs", [])
        if candidate.get("route_id") != route_id or not isinstance(objective, str) or not objective:
            raise ValueError("objective candidate escaped its frozen output route")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("objective candidate evidence_refs must be strings")
        result.append({"route_id": route_id, "objective": objective, "evidence_refs": list(refs)})
    return tuple(result)
