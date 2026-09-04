"""Recognize an exact Calendar CREATE contract that adds no new Review semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def is_exact_calendar_create_plan(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    tool_route_plan: Mapping[str, object] | None = None,
) -> bool:
    """Return true only when one action exactly materializes the validated intent."""
    if (
        request_intent.get("requested_resource_hints") != ["CALENDAR_EVENT"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return False
    ambiguity = request_intent.get("ambiguity")
    if not isinstance(ambiguity, Mapping) or ambiguity.get("requires_confirmation") is not False:
        return False
    values = _exact_constraint_values(request_intent.get("constraints"))
    if values is None:
        return False
    expected_start = _local_datetime(values["date"], values["start_time"], values["timezone"])
    expected_end = _local_datetime(values["date"], values["end_time"], values["timezone"])
    if expected_start is None or expected_end is None or expected_end <= expected_start:
        return False

    actions = planning_result.get("actions")
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], Mapping):
        return False
    action = actions[0]
    arguments = action.get("arguments")
    if (
        action.get("tool_id") != "calendar_create_event"
        or action.get("effect") != "CREATE"
        or not isinstance(action.get("route_id"), str)
        or not isinstance(arguments, Mapping)
        or set(arguments) != {"calendar_id", "payload"}
        or arguments.get("calendar_id") != "primary"
    ):
        return False
    payload = arguments.get("payload")
    if not isinstance(payload, Mapping) or set(payload) != {"title", "start", "end"}:
        return False
    if payload.get("title") != values["title"]:
        return False
    actual_start = _iso_datetime(payload.get("start"))
    actual_end = _iso_datetime(payload.get("end"))
    if actual_start != expected_start or actual_end != expected_end:
        return False
    if tool_route_plan is None:
        return True
    return _matches_frozen_route(tool_route_plan, route_id=str(action["route_id"]))


def _exact_constraint_values(value: object) -> dict[str, str] | None:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return None
    expected = {
        "title": "RESOURCE",
        "date": "DATE",
        "start_time": "TIME",
        "end_time": "TIME",
        "timezone": "TIME",
    }
    values: dict[str, str] = {}
    for item in value:
        if not isinstance(item, Mapping):
            return None
        field = item.get("field")
        item_value = item.get("value")
        if (
            not isinstance(field, str)
            or field not in expected
            or item.get("kind") != expected[field]
            or not isinstance(item_value, str)
            or not item_value
            or field in values
        ):
            return None
        values[field] = item_value
    return values if set(values) == set(expected) else None


def _local_datetime(date_value: str, time_value: str, timezone_name: str) -> datetime | None:
    try:
        return datetime.fromisoformat(f"{date_value}T{time_value}").replace(
            tzinfo=ZoneInfo(timezone_name)
        )
    except (ValueError, ZoneInfoNotFoundError):
        return None


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _matches_frozen_route(tool_route_plan: Mapping[str, object], *, route_id: str) -> bool:
    output_plan = tool_route_plan.get("output_plan")
    if not isinstance(output_plan, Mapping) or output_plan.get("output_mode") != "ACTION":
        return False
    routes = output_plan.get("output_routes")
    if not isinstance(routes, list) or len(routes) != 1 or not isinstance(routes[0], Mapping):
        return False
    route = routes[0]
    return (
        route.get("route_id") == route_id
        and route.get("resource_type") == "CALENDAR_EVENT"
        and route.get("connector_id") == "google_workspace"
        and route.get("effect") == "CREATE"
        and route.get("selected_tool_id") == "calendar_create_event"
    )


__all__ = ["is_exact_calendar_create_plan"]
