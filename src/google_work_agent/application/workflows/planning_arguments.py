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
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.schema_validation import validate_output_schema
from google_work_agent.application.workflows.tool_routing import OutputToolRouteV1

JsonObject = dict[str, object]


class PlanningArgumentBindingError(ValueError):
    """Raised when a Planning argument candidate escapes its frozen route."""


class RequiredContainerUnresolvedError(PlanningArgumentBindingError):
    """The selected Tool requires a container but no deterministic binding exists."""

    def __init__(self, *, route_id: str, tool_id: str, argument_name: str) -> None:
        super().__init__(f"{argument_name} is required for selected tool: {tool_id}")
        self.route_id = route_id
        self.tool_id = tool_id
        self.argument_name = argument_name


class BoundSelectedToolSchemaV1(TypedDict):
    """One frozen output route plus its immutable selected Tool schema."""

    schema_version: Required[Literal[1]]
    route_id: str
    connector_id: str
    resource_type: str
    effect: str
    selected_tool_id: str
    argument_schema: JsonObject
    immutable_arguments: dict[str, object]


class ToolArgumentCandidateV1(TypedDict):
    """Thin LLM-owned business arguments for exactly one output route."""

    schema_version: Required[Literal[1]]
    route_id: str
    arguments: dict[str, object]
    evidence_refs: list[str]


_CONTAINER_ARGUMENT_BY_TOOL: dict[str, str] = {
    "tasks_create_task": "task_list_id",
    "tasks_update_task": "task_list_id",
    "tasks_delete_task": "task_list_id",
    "calendar_create_event": "calendar_id",
    "calendar_update_event": "calendar_id",
    "calendar_delete_event": "calendar_id",
}


class DefaultContainerResolver:
    """Resolve connector container ids without giving that authority to an LLM."""

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
        """Return a schema whose required container field is immutable/``const``.

        An explicitly selected container wins over the configured default. If
        the selected Tool requires a container and neither source provides one,
        the typed unresolved-container error is raised before an Argument Writer
        can be called.
        """

        tool_id = route["selected_tool_id"]
        container_argument = _CONTAINER_ARGUMENT_BY_TOOL.get(tool_id)
        immutable_arguments: dict[str, object] = {}
        schema = _mapping_copy(selected_tool_schema, "selected_tool_schema")

        if container_argument is not None:
            container_id = _normalized_optional_string(explicit_container_id)
            if container_id is None:
                container_id = self._configured_default(container_argument)
            if container_id is None:
                raise RequiredContainerUnresolvedError(
                    route_id=route["route_id"],
                    tool_id=tool_id,
                    argument_name=container_argument,
                )
            schema = _bind_schema_const(
                schema,
                argument_name=container_argument,
                argument_value=container_id,
            )
            immutable_arguments[container_argument] = container_id

        return {
            "schema_version": 1,
            "route_id": route["route_id"],
            "connector_id": route["connector_id"],
            "resource_type": route["resource_type"],
            "effect": route["effect"],
            "selected_tool_id": tool_id,
            "argument_schema": schema,
            "immutable_arguments": immutable_arguments,
        }

    def _configured_default(self, argument_name: str) -> str | None:
        provider: Callable[[], str | None] | None
        if argument_name == "task_list_id":
            provider = self._default_tasklist_id_provider
        elif argument_name == "calendar_id":
            provider = self._default_calendar_id_provider
        else:  # pragma: no cover - protected by the static tool mapping above.
            raise PlanningArgumentBindingError(
                f"unsupported deterministic container argument: {argument_name}"
            )
        if provider is None:
            return None
        return _normalized_optional_string(provider())


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

    schema_errors = validate_output_schema(arguments, bound_tool_schema["argument_schema"])
    if schema_errors:
        raise PlanningArgumentBindingError(
            "argument candidate does not satisfy selected Tool schema: "
            + "; ".join(schema_errors[:8])
        )

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


def _bind_schema_const(
    schema: JsonObject,
    *,
    argument_name: str,
    argument_value: str,
) -> JsonObject:
    bound = deepcopy(schema)
    if bound.get("type") != "object":
        raise PlanningArgumentBindingError("selected Tool argument schema must be an object")
    properties = bound.get("properties")
    if not isinstance(properties, dict):
        raise PlanningArgumentBindingError("selected Tool argument schema must define properties")
    raw_property = properties.get(argument_name)
    if not isinstance(raw_property, dict):
        raise PlanningArgumentBindingError(
            f"selected Tool schema is missing required container field: {argument_name}"
        )
    property_schema = dict(cast(dict[str, object], raw_property))
    existing_const = property_schema.get("const")
    if existing_const is not None and existing_const != argument_value:
        raise PlanningArgumentBindingError(
            f"selected Tool schema has conflicting const for {argument_name}"
        )
    property_schema["const"] = argument_value
    properties[argument_name] = property_schema

    required = bound.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise PlanningArgumentBindingError("selected Tool schema required must be a string list")
    if argument_name not in required:
        bound["required"] = [*cast(list[str], required), argument_name]
    return bound


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


def _normalized_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


__all__ = [
    "BoundSelectedToolSchemaV1",
    "DefaultContainerResolver",
    "PlanningArgumentBindingError",
    "RequiredContainerUnresolvedError",
    "ToolArgumentCandidateV1",
    "validate_tool_argument_candidate_v1",
]
