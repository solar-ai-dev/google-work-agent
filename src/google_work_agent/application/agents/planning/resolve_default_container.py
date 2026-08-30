"""Deterministically bind a selected Tool's required container argument."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Literal, Required, TypedDict, cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    OutputToolRouteV1,
)

JsonObject = dict[str, object]


class PlanningArgumentBindingError(ValueError):
    """A Planning argument projection escaped its frozen Tool route."""


class RequiredContainerUnresolvedError(PlanningArgumentBindingError):
    """The selected Tool requires a container with no deterministic source."""

    def __init__(self, *, route_id: str, tool_id: str, argument_name: str) -> None:
        super().__init__(f"{argument_name} is required for selected tool: {tool_id}")
        self.route_id = route_id
        self.tool_id = tool_id
        self.argument_name = argument_name


class BoundSelectedToolSchemaV1(TypedDict):
    schema_version: Required[Literal[1]]
    route_id: str
    connector_id: str
    resource_type: str
    effect: str
    selected_tool_id: str
    argument_schema: JsonObject
    immutable_arguments: dict[str, object]


_CONTAINER_ARGUMENT_BY_TOOL = {
    "tasks_create_task": "task_list_id",
    "tasks_update_task": "task_list_id",
    "tasks_delete_task": "task_list_id",
    "calendar_create_event": "calendar_id",
    "calendar_update_event": "calendar_id",
    "calendar_delete_event": "calendar_id",
}


def resolve_default_container(
    *,
    route: OutputToolRouteV1,
    selected_tool_schema: Mapping[str, object],
    explicit_container_id: str | None = None,
    default_tasklist_id_provider: Callable[[], str | None] | None = None,
    default_calendar_id_provider: Callable[[], str | None] | None = None,
) -> BoundSelectedToolSchemaV1:
    """Const-bind explicit/configured container identity before Prompt invocation."""

    schema = _mapping_copy(selected_tool_schema, "selected_tool_schema")
    tool_id = route["selected_tool_id"]
    argument_name = _CONTAINER_ARGUMENT_BY_TOOL.get(tool_id)
    immutable_arguments: dict[str, object] = {}
    if argument_name is not None:
        container_id = _normalized(explicit_container_id)
        if container_id is None:
            provider = (
                default_tasklist_id_provider
                if argument_name == "task_list_id"
                else default_calendar_id_provider
            )
            container_id = None if provider is None else _normalized(provider())
        if container_id is None:
            raise RequiredContainerUnresolvedError(
                route_id=route["route_id"],
                tool_id=tool_id,
                argument_name=argument_name,
            )
        schema = _bind_const(schema, argument_name, container_id)
        immutable_arguments[argument_name] = container_id
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


def _bind_const(schema: JsonObject, name: str, value: str) -> JsonObject:
    bound = deepcopy(schema)
    if bound.get("type") != "object" or not isinstance(bound.get("properties"), dict):
        raise PlanningArgumentBindingError("selected Tool argument schema must be an object")
    properties = cast(dict[str, object], bound["properties"])
    raw = properties.get(name)
    if not isinstance(raw, dict):
        raise PlanningArgumentBindingError(
            f"selected Tool schema is missing required container field: {name}"
        )
    prop = dict(raw)
    if prop.get("const") not in (None, value):
        raise PlanningArgumentBindingError(f"selected Tool schema has conflicting const for {name}")
    prop["const"] = value
    properties[name] = prop
    required = bound.get("required", [])
    if not isinstance(required, list) or not all(isinstance(item, str) for item in required):
        raise PlanningArgumentBindingError("selected Tool schema required must be a string list")
    if name not in required:
        bound["required"] = [*required, name]
    return bound


def _mapping_copy(value: Mapping[str, object], path: str) -> JsonObject:
    result: JsonObject = {}
    for key, item in value.items():
        if not isinstance(key, str):
            raise PlanningArgumentBindingError(f"{path} keys must be strings")
        result[key] = deepcopy(item)
    return result


def _normalized(value: object) -> str | None:
    return value.strip() or None if isinstance(value, str) else None


__all__ = [
    "BoundSelectedToolSchemaV1",
    "PlanningArgumentBindingError",
    "RequiredContainerUnresolvedError",
    "resolve_default_container",
]
