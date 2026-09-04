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
    deterministic_evidence_refs = [
        ref
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    ]
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        candidate: Mapping[str, object] | None = _deterministic_create_objective(
            route=route,
            request_intent=request_intent,
        )
        if candidate is not None:
            candidate = {
                **candidate,
                "evidence_refs": list(dict.fromkeys(deterministic_evidence_refs)),
            }
        if candidate is None:
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


def requires_objective_inference(
    route: Mapping[str, object], *, request_intent: Mapping[str, object]
) -> bool:
    return (
        _deterministic_create_objective(
            route=route,
            request_intent=request_intent,
        )
        is None
    )


def _deterministic_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    return _deterministic_calendar_create_objective(
        route=route,
        request_intent=request_intent,
    ) or _deterministic_task_create_objective(
        route=route,
        request_intent=request_intent,
    )


def _deterministic_calendar_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    route_id = route.get("route_id")
    if (
        route.get("resource_type") != "CALENDAR_EVENT"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "calendar_create_event"
        or not isinstance(route_id, str)
        or request_intent.get("requested_resource_hints") != ["CALENDAR_EVENT"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return None
    ambiguity = request_intent.get("ambiguity")
    if isinstance(ambiguity, Mapping) and ambiguity.get("requires_confirmation") is True:
        return None
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return None
    scope_constraints: list[str] = []
    for item in constraints:
        if not isinstance(item, Mapping):
            return None
        field, value = item.get("field"), item.get("value")
        if not isinstance(field, str) or not isinstance(value, str):
            return None
        scope_constraints.append(f"{field}: {value}")
    if not scope_constraints:
        return None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "objective": "Create the exact calendar event specified by the validated request intent.",
        "target_semantics": "CALENDAR_EVENT",
        "scope_constraints": scope_constraints,
        "evidence_refs": [],
    }


def _deterministic_task_create_objective(
    *, route: Mapping[str, object], request_intent: Mapping[str, object]
) -> ActionObjectiveCandidateV1 | None:
    route_id = route.get("route_id")
    if (
        route.get("resource_type") != "TASK"
        or route.get("effect") != "CREATE"
        or route.get("selected_tool_id") != "tasks_create_task"
        or not isinstance(route_id, str)
        or request_intent.get("requested_resource_hints") != ["TASK"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return None
    ambiguity = request_intent.get("ambiguity")
    if not isinstance(ambiguity, Mapping) or ambiguity.get("requires_confirmation") is not False:
        return None
    constraints = request_intent.get("constraints")
    if (
        not isinstance(constraints, Sequence)
        or isinstance(constraints, (str, bytes))
        or len(constraints) != 1
    ):
        return None
    title = constraints[0]
    if (
        not isinstance(title, Mapping)
        or title.get("kind") != "RESOURCE"
        or title.get("field") != "title"
        or not isinstance(title.get("value"), str)
        or not title["value"]
    ):
        return None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "objective": "Create the exact task specified by the validated request intent.",
        "target_semantics": "TASK",
        "scope_constraints": [f"title: {title['value']}"],
        "evidence_refs": [],
    }


__all__ = [
    "ACTION_OBJECTIVE_CANDIDATE_OUTPUT_SCHEMA",
    "draft_action_objective_per_output_route",
    "requires_objective_inference",
]
