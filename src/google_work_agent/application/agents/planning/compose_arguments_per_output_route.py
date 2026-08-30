"""Compose business arguments per frozen output route without route reselection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

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
from google_work_agent.ports.llm import OutputSchemaDefinition

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
                "minItems": 1,
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
        prompt_input: dict[str, object] = {
            "output_route": dict(route),
            "action_objective": dict(objective),
            "tool_schema": dict(bound_schema["argument_schema"]),
            "evidence": [dict(item) for item in evidence],
        }
        if work_analysis is not None:
            prompt_input["work_analysis"] = dict(work_analysis)
        if confirmation_response is not None:
            prompt_input["confirmation_response"] = dict(confirmation_response)
        candidate = invoke(
            PROMPT_ID,
            prompt_input,
        )
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
        if not refs or len(refs) != len(set(refs)) or not set(refs).issubset(allowed_refs):
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


__all__ = ["TOOL_ARGUMENT_CANDIDATE_OUTPUT_SCHEMA", "compose_arguments_per_output_route"]
