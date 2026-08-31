"""Deterministic Planning argument binding for one frozen output route.

Planning's LLM argument writer is not allowed to choose another Tool or to
invent connector container identifiers. This module owns the deterministic
boundary that binds configured/explicit container ids into the selected Tool
schema before that schema is exposed to the argument writer, and validates the
writer's thin ``ToolArgumentCandidateV1`` against the same frozen route.

The module deliberately does not own Tool selection or final ActionPlan
assembly. Tool Route owns ``selected_tool_id``/``effect``; Planning's caller
will later assemble the validated per-route candidates deterministically.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import cast

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    ToolArgumentCandidateV1,
)
from google_work_agent.application.agents.planning.resolve_default_container import (
    BoundSelectedToolSchemaV1,
    PlanningArgumentBindingError,
    RequiredContainerUnresolvedError,
    resolve_default_container,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)
from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
    ValidateActionArgumentsQueryV1,
)

JsonObject = dict[str, object]


class DefaultContainerResolver:
    """Legacy fused-profile adapter delegating to the exact CAP-AGT-030 owner."""

    def __init__(
        self,
        *,
        default_tasklist_id_provider: Callable[[], str | None] | None = None,
        default_calendar_id_provider: Callable[[], str | None] | None = None,
    ) -> None:
        self._default_tasklist_id_provider = default_tasklist_id_provider
        self._default_calendar_id_provider = default_calendar_id_provider

    def bind_selected_tool_schema(
        self,
        *,
        route: OutputToolRouteV1,
        selected_tool_schema: Mapping[str, object],
        explicit_container_id: str | None = None,
    ) -> BoundSelectedToolSchemaV1:
        return resolve_default_container(
            route=route,
            selected_tool_schema=selected_tool_schema,
            explicit_container_id=explicit_container_id,
            default_tasklist_id_provider=self._default_tasklist_id_provider,
            default_calendar_id_provider=self._default_calendar_id_provider,
        )


def validate_tool_argument_candidate_v1(
    value: object,
    *,
    bound_tool_schema: BoundSelectedToolSchemaV1,
    allowed_evidence_refs: set[str],
) -> ToolArgumentCandidateV1:
    """Validate one LLM candidate against its frozen route and immutable binding."""

    candidate = _require_mapping(value, "candidate")
    required_keys = {"schema_version", "route_id", "arguments", "evidence_refs"}
    if set(candidate) != required_keys:
        raise PlanningArgumentBindingError(
            "ToolArgumentCandidateV1 must contain only schema_version, route_id, "
            "arguments, evidence_refs"
        )
    if candidate["schema_version"] != 1:
        raise PlanningArgumentBindingError("ToolArgumentCandidateV1.schema_version must be 1")
    if candidate["route_id"] != bound_tool_schema["route_id"]:
        raise PlanningArgumentBindingError("argument candidate route_id escapes frozen route")

    arguments = _require_mapping(candidate["arguments"], "candidate.arguments")
    for name, expected in bound_tool_schema["immutable_arguments"].items():
        actual = arguments.get(name)
        if actual is not None and actual != expected:
            raise PlanningArgumentBindingError(
                f"argument candidate attempts to override immutable {name}"
            )
        arguments[name] = expected

    validation = ValidateActionArgumentsHandler()(
        ValidateActionArgumentsQueryV1(arguments, bound_tool_schema["argument_schema"])
    )
    if not validation.valid:
        raise PlanningArgumentBindingError(
            "argument candidate does not satisfy selected Tool schema: "
            + "; ".join(validation.error_paths[:8])
        )
    arguments = validation.normalized_arguments

    evidence_refs = _require_string_list(candidate["evidence_refs"], "candidate.evidence_refs")
    if not evidence_refs:
        raise PlanningArgumentBindingError("argument candidate requires at least one evidence ref")
    unknown_evidence = set(evidence_refs) - allowed_evidence_refs
    if unknown_evidence:
        raise PlanningArgumentBindingError("argument candidate references unavailable evidence")

    return {
        "schema_version": 1,
        "route_id": cast(str, candidate["route_id"]),
        "arguments": arguments,
        "evidence_refs": evidence_refs,
    }


def _mapping_copy(value: Mapping[str, object], path: str) -> JsonObject:
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlanningArgumentBindingError(f"{path} keys must be strings")
        result[key] = deepcopy(item)
    return result


def _require_mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise PlanningArgumentBindingError(f"{path} must be an object")
    return _mapping_copy(cast(Mapping[str, object], value), path)


def _require_string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise PlanningArgumentBindingError(f"{path} must be a list of non-empty strings")
    result = cast(list[str], list(value))
    if len(result) != len(set(result)):
        raise PlanningArgumentBindingError(f"{path} must not contain duplicates")
    return result


__all__ = [
    "BoundSelectedToolSchemaV1",
    "DefaultContainerResolver",
    "PlanningArgumentBindingError",
    "RequiredContainerUnresolvedError",
    "ToolArgumentCandidateV1",
    "validate_tool_argument_candidate_v1",
]
