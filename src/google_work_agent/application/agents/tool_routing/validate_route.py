from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    ToolRoutePlanV2,
)
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.domain.action.model import EffectType


class ToolRouteValidationError(ValueError):
    """Raised when Tool Routing violates the frozen Registry-bound contract."""


def validate_route(value: object, *, tool_catalog: SignedToolRegistry) -> ToolRoutePlanV2:
    root = _mapping(value, "$")
    if set(root) != {"schema_version", "input_plan", "output_plan", "tool_registry_version"}:
        raise ToolRouteValidationError("ToolRoutePlanV2 fields are invalid")
    if root.get("schema_version") != 2:
        raise ToolRouteValidationError("ToolRoutePlanV2.schema_version must be 2")
    registry_version = _string(root, "tool_registry_version")
    input_plan = _mapping(root.get("input_plan"), "$.input_plan")
    output_plan = _mapping(root.get("output_plan"), "$.output_plan")
    _validate_plan_meta(input_plan, "$.input_plan")
    _validate_plan_meta(output_plan, "$.output_plan")
    input_routes = input_plan.get("input_routes")
    if not isinstance(input_routes, list):
        raise ToolRouteValidationError("$.input_plan.input_routes must be a list")
    route_ids: set[str] = set()
    for index, raw_route in enumerate(input_routes):
        route = _mapping(raw_route, f"$.input_plan.input_routes[{index}]")
        if set(route) != {
            "route_id",
            "resource_type",
            "connector_id",
            "allowed_read_tool_ids",
            "required",
            "reason_codes",
        }:
            raise ToolRouteValidationError("input route fields are invalid")
        _validate_route_id(route, route_ids)
        connector_id = _string(route, "connector_id")
        resource_type = _string(route, "resource_type")
        tool_ids = route.get("allowed_read_tool_ids")
        if not isinstance(tool_ids, list) or not tool_ids:
            raise ToolRouteValidationError("input route requires allowed_read_tool_ids")
        if not isinstance(route.get("required"), bool):
            raise ToolRouteValidationError("input route required must be boolean")
        _validate_reason_codes(route)
        for tool_id in tool_ids:
            if not isinstance(tool_id, str):
                raise ToolRouteValidationError("allowed_read_tool_ids must contain strings")
            entry = tool_catalog.get_required(connector_id=connector_id, tool_id=tool_id)
            if entry.effect_type is not EffectType.READ or entry.resource_type != resource_type:
                raise ToolRouteValidationError("input route tool binding is invalid")
            if entry.registry_version != registry_version:
                raise ToolRouteValidationError("input route registry version is stale")
    output_mode = output_plan.get("output_mode")
    if output_mode == "ANSWER":
        if "output_routes" in output_plan:
            raise ToolRouteValidationError("ANSWER output must not contain output_routes")
    elif output_mode == "ACTION":
        output_routes = output_plan.get("output_routes")
        if not isinstance(output_routes, list) or not output_routes:
            raise ToolRouteValidationError("ACTION output requires output_routes")
        for raw_route in output_routes:
            route = _mapping(raw_route, "$.output_plan.output_routes[]")
            if set(route) != {
                "route_id",
                "resource_type",
                "connector_id",
                "effect",
                "selected_tool_id",
                "reason_codes",
            }:
                raise ToolRouteValidationError("output route fields are invalid")
            _validate_route_id(route, route_ids)
            _validate_reason_codes(route)
            connector_id = _string(route, "connector_id")
            resource_type = _string(route, "resource_type")
            tool_id = _string(route, "selected_tool_id")
            try:
                effect = EffectType(_string(route, "effect"))
            except ValueError as error:
                raise ToolRouteValidationError("output route effect is invalid") from error
            if effect is EffectType.READ:
                raise ToolRouteValidationError("output route effect must be a write effect")
            entry = tool_catalog.get_required(connector_id=connector_id, tool_id=tool_id)
            if entry.effect_type is not effect or entry.resource_type != resource_type:
                raise ToolRouteValidationError("output route tool binding is invalid")
            if entry.registry_version != registry_version:
                raise ToolRouteValidationError("output route registry version is stale")
    else:
        raise ToolRouteValidationError("output_mode is invalid")
    return cast(ToolRoutePlanV2, value)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ToolRouteValidationError(f"{path} must be an object")
    return cast(Mapping[str, object], value)


def _string(value: Mapping[str, object], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item:
        raise ToolRouteValidationError(f"{key} must be a non-empty string")
    return item


def _validate_plan_meta(value: Mapping[str, object], path: str) -> None:
    if value.get("schema_version") != 1:
        raise ToolRouteValidationError(f"{path}.schema_version must be 1")
    meta = _mapping(value.get("meta"), f"{path}.meta")
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise ToolRouteValidationError(f"{path}.meta fields are invalid")
    if (
        not isinstance(meta.get("artifact_id"), str)
        or not meta["artifact_id"]
        or not isinstance(meta.get("revision"), int)
        or cast(int, meta["revision"]) < 1
    ):
        raise ToolRouteValidationError(f"{path}.meta is invalid")
    based_on = meta.get("based_on")
    if not isinstance(based_on, list) or not based_on:
        raise ToolRouteValidationError(f"{path}.meta.based_on is required")
    for reference in based_on:
        item = _mapping(reference, f"{path}.meta.based_on[]")
        if set(item) != {"artifact_id", "revision"}:
            raise ToolRouteValidationError(f"{path}.meta.based_on fields are invalid")
        if not isinstance(item.get("artifact_id"), str) or not isinstance(
            item.get("revision"), int
        ):
            raise ToolRouteValidationError(f"{path}.meta.based_on is invalid")


def _validate_route_id(route: Mapping[str, object], route_ids: set[str]) -> None:
    route_id = _string(route, "route_id")
    if route_id in route_ids:
        raise ToolRouteValidationError(f"duplicate route_id: {route_id}")
    route_ids.add(route_id)


def _validate_reason_codes(route: Mapping[str, object]) -> None:
    reason_codes = route.get("reason_codes")
    if not isinstance(reason_codes, list) or not all(
        isinstance(item, str) for item in reason_codes
    ):
        raise ToolRouteValidationError("route reason_codes must contain strings")
