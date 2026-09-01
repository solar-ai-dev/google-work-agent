"""Draft one bounded business objective for each frozen output route."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    PlanningSemanticInvoker,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.draft_action_objective_per_output_route"

ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-action-objective-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "schema_version",
            "route_id",
            "objective",
            "target_semantics",
            "scope_constraints",
            "evidence_refs",
        ],
        "properties": {
            "schema_version": {"const": 1},
            "route_id": {"type": "string", "minLength": 1},
            "objective": {"type": "string", "minLength": 1},
            "target_semantics": {"type": "string", "minLength": 1},
            "scope_constraints": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


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
    allowed_refs = {
        ref
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    }
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        prompt_input: dict[str, object] = {
            "user_request": user_request,
            "request_intent": dict(request_intent),
            "output_route": dict(route),
            "evidence": [dict(item) for item in evidence],
        }
        if work_analysis is not None:
            prompt_input["work_analysis"] = dict(work_analysis)
        candidate = invoke(PROMPT_ID, prompt_input)
        objective = candidate.get("objective")
        target_semantics = candidate.get("target_semantics")
        scope_constraints = candidate.get("scope_constraints")
        refs = candidate.get("evidence_refs", [])
        if candidate.get("schema_version") != 1:
            raise ValueError("objective candidate requires schema_version 1")
        if candidate.get("route_id") != route_id or not isinstance(objective, str) or not objective:
            raise ValueError("objective candidate escaped its frozen output route")
        if not isinstance(target_semantics, str) or not target_semantics:
            raise ValueError("objective candidate requires target_semantics")
        if not isinstance(scope_constraints, list) or not all(
            isinstance(item, str) and item for item in scope_constraints
        ):
            raise ValueError("objective candidate scope_constraints must be strings")
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("objective candidate evidence_refs must be strings")
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_refs):
            raise ValueError("objective candidate references unavailable evidence")
        result.append(
            {
                "schema_version": 1,
                "route_id": route_id,
                "objective": objective,
                "target_semantics": target_semantics,
                "scope_constraints": list(scope_constraints),
                "evidence_refs": list(refs),
            }
        )
    return tuple(result)


__all__ = ["ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA", "draft_action_objective_per_output_route"]
