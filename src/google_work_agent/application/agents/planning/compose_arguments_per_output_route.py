"""Compose business arguments per frozen output route without route reselection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ActionObjectiveCandidateV1,
    PlanningSemanticInvoker,
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
)
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
    ValidateActionArgumentsQueryV1,
)
from google_work_agent.ports.llm.structured_inference_contracts import OutputSchemaDefinition

PROMPT_ID = "planning.compose_arguments_per_output_route"

TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA = OutputSchemaDefinition(
    schema_version="planning-tool-argument-candidate-v1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "route_id", "arguments", "evidence_refs"],
        "properties": {
            "schema_version": {"const": 1},
            "route_id": {"type": "string", "minLength": 1},
            "arguments": {"type": "object"},
            "evidence_refs": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
            },
        },
    },
)


def compose_arguments_per_output_route(
    output_routes: Sequence[Mapping[str, object]],
    *,
    objectives: Sequence[ActionObjectiveCandidateV1],
    bound_tool_schemas: Sequence[BoundSelectedToolSchemaV1],
    request_intent: Mapping[str, object] | None = None,
    work_analysis: Mapping[str, object] | None = None,
    evidence: Sequence[Mapping[str, object]] = (),
    invoke: PlanningSemanticInvoker,
    confirmation_response: Mapping[str, object] | None = None,
) -> tuple[ToolArgumentCandidateV1, ...]:
    """Execute exactly one canonical semantic path for every frozen output route."""
    if not output_routes:
        raise ValueError("ACTION planning requires at least one output route")
    objective_by_route = {item["route_id"]: item for item in objectives}
    if len(objective_by_route) != len(objectives):
        raise ValueError("duplicate objective route")
    schema_by_route = {item["route_id"]: item for item in bound_tool_schemas}
    if len(schema_by_route) != len(bound_tool_schemas):
        raise ValueError("duplicate selected Tool schema route")
    allowed_refs = {
        ref
        for item in evidence
        for ref in (item.get("evidence_ref") or item.get("evidence_id") or item.get("id"),)
        if isinstance(ref, str) and ref
    }
    candidates: list[ToolArgumentCandidateV1] = []
    seen: set[str] = set()
    for route in output_routes:
        route_id = route.get("route_id")
        if not isinstance(route_id, str) or not route_id or route_id in seen:
            raise ValueError("output route_id must be unique and non-empty")
        seen.add(route_id)
        objective = objective_by_route.get(route_id)
        bound_schema = schema_by_route.get(route_id)
        if objective is None or bound_schema is None:
            raise ValueError("every canonical output route requires an objective and Tool schema")
        if (
            bound_schema["selected_tool_id"] != route.get("selected_tool_id")
            or bound_schema["connector_id"] != route.get("connector_id")
            or bound_schema["effect"] != route.get("effect")
        ):
            raise ValueError("bound Tool schema escaped frozen route identity")
        candidate: Mapping[str, object] | None = _deterministic_argument_candidate(
            route=route,
            request_intent=request_intent,
            allowed_refs=allowed_refs,
            objective=objective,
        )
        if candidate is None:
            prompt_input: dict[str, object] = {
                "output_route": dict(route),
                "action_objective": dict(objective),
                "tool_schema": dict(bound_schema["argument_schema"]),
                "evidence": [dict(item) for item in evidence],
            }
            if request_intent is not None:
                prompt_input["request_intent"] = dict(request_intent)
            if work_analysis is not None:
                prompt_input["work_analysis"] = dict(work_analysis)
            if confirmation_response is not None:
                prompt_input["confirmation_response"] = dict(confirmation_response)
            candidate = invoke(PROMPT_ID, prompt_input)
        if candidate.get("schema_version") != 1 or candidate.get("route_id") != route_id:
            raise ValueError("argument candidate escaped its frozen output route")
        arguments = candidate.get("arguments")
        refs = candidate.get("evidence_refs", [])
        if not isinstance(arguments, dict):
            raise ValueError("argument candidate requires business arguments")
        arguments = dict(arguments)
        for name, expected in bound_schema["immutable_arguments"].items():
            actual = arguments.get(name)
            if actual is not None and actual != expected:
                raise PlanningArgumentBindingError(
                    f"argument candidate attempts to override immutable {name}"
                )
            arguments[name] = expected
        validation = ValidateActionArgumentsHandler()(
            ValidateActionArgumentsQueryV1(arguments, bound_schema["argument_schema"])
        )
        if not validation.valid:
            raise PlanningArgumentBindingError(
                "argument candidate does not satisfy selected Tool schema: "
                + "; ".join(validation.error_paths[:8])
            )
        if not isinstance(refs, list) or not all(isinstance(item, str) for item in refs):
            raise ValueError("argument candidate evidence_refs must be strings")
        if len(refs) != len(set(refs)) or not set(refs).issubset(allowed_refs):
            raise PlanningArgumentBindingError("argument candidate references unavailable evidence")
        candidates.append(
            {
                "schema_version": 1,
                "route_id": route_id,
                "arguments": cast(dict[str, object], validation.normalized_arguments),
                "evidence_refs": list(refs),
            }
        )
    return tuple(candidates)


def requires_argument_inference(
    route: Mapping[str, object], *, request_intent: Mapping[str, object] | None
) -> bool:
    return _deterministic_create_payload(route=route, request_intent=request_intent) is None


def _deterministic_argument_candidate(
    *,
    route: Mapping[str, object],
    request_intent: Mapping[str, object] | None,
    allowed_refs: set[str],
    objective: ActionObjectiveCandidateV1,
) -> ToolArgumentCandidateV1 | None:
    payload = _deterministic_create_payload(route=route, request_intent=request_intent)
    route_id = route.get("route_id")
    if payload is None or not isinstance(route_id, str):
        return None
    return {
        "schema_version": 1,
        "route_id": route_id,
        "arguments": {"payload": payload},
        "evidence_refs": [
            ref for ref in objective.get("evidence_refs", []) if ref in allowed_refs
        ],
    }


def _deterministic_create_payload(
    *, route: Mapping[str, object], request_intent: Mapping[str, object] | None
) -> dict[str, object] | None:
    return _calendar_create_payload(
        route=route,
        request_intent=request_intent,
    ) or _task_create_payload(
        route=route,
        request_intent=request_intent,
    )


def _calendar_create_payload(
    *, route: Mapping[str, object], request_intent: Mapping[str, object] | None
) -> dict[str, object] | None:
    if (
        route.get("selected_tool_id") != "calendar_create_event"
        or route.get("effect") != "CREATE"
        or not isinstance(request_intent, Mapping)
    ):
        return None
    ambiguity = request_intent.get("ambiguity")
    if isinstance(ambiguity, Mapping) and ambiguity.get("requires_confirmation") is True:
        return None
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, Sequence) or isinstance(constraints, (str, bytes)):
        return None
    values: dict[str, str] = {}
    for item in constraints:
        if not isinstance(item, Mapping):
            return None
        kind, field, value = item.get("kind"), item.get("field"), item.get("value")
        if kind in {"PERSON", "EMAIL"}:
            return None
        if not isinstance(field, str) or not isinstance(value, str):
            continue
        if field in {"title", "date", "start_time", "end_time", "timezone"}:
            if field in values and values[field] != value:
                return None
            values[field] = value
    required = {"title", "date", "start_time", "end_time", "timezone"}
    if not required.issubset(values):
        return None
    start = _aware_calendar_datetime(values["date"], values["start_time"], values["timezone"])
    end = _aware_calendar_datetime(values["date"], values["end_time"], values["timezone"])
    if start is None or end is None or end <= start:
        return None
    return {
        "title": values["title"],
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
    }


def _task_create_payload(
    *, route: Mapping[str, object], request_intent: Mapping[str, object] | None
) -> dict[str, object] | None:
    if (
        route.get("resource_type") != "TASK"
        or route.get("selected_tool_id") != "tasks_create_task"
        or route.get("effect") != "CREATE"
        or not isinstance(request_intent, Mapping)
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
    return {"title": title["value"]}


def _aware_calendar_datetime(
    calendar_date: str, local_time: str, timezone_name: str
) -> datetime | None:
    try:
        timezone = ZoneInfo(timezone_name)
        value = local_time if "T" in local_time else f"{calendar_date}T{local_time}"
        parsed = datetime.fromisoformat(value)
    except (ValueError, ZoneInfoNotFoundError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


__all__ = [
    "TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA",
    "compose_arguments_per_output_route",
    "requires_argument_inference",
]
