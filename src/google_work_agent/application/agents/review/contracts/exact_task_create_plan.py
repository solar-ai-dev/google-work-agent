"""Recognize an exact Task CREATE contract that adds no new Review semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence


def is_exact_task_create_plan(
    *,
    request_intent: Mapping[str, object],
    planning_result: Mapping[str, object],
    work_analysis: Mapping[str, object] | None,
    tool_route_plan: Mapping[str, object] | None = None,
) -> bool:
    """Return true only for an exact title create with a clean duplicate analysis."""
    if (
        request_intent.get("requested_resource_hints") != ["TASK"]
        or request_intent.get("requested_effect_hints") != ["CREATE"]
    ):
        return False
    ambiguity = request_intent.get("ambiguity")
    if not isinstance(ambiguity, Mapping) or ambiguity.get("requires_confirmation") is not False:
        return False
    title = _exact_title(request_intent.get("constraints"))
    if title is None:
        return False

    actions = planning_result.get("actions")
    if not isinstance(actions, list) or len(actions) != 1 or not isinstance(actions[0], Mapping):
        return False
    action = actions[0]
    arguments = action.get("arguments")
    if (
        action.get("tool_id") != "tasks_create_task"
        or action.get("effect") != "CREATE"
        or not isinstance(action.get("route_id"), str)
        or not isinstance(arguments, Mapping)
        or set(arguments) != {"task_list_id", "payload"}
        or not isinstance(arguments.get("task_list_id"), str)
        or not arguments["task_list_id"]
    ):
        return False
    payload = arguments.get("payload")
    if (
        not isinstance(payload, Mapping)
        or set(payload) != {"title"}
        or payload.get("title") != title
    ):
        return False
    if not _has_clean_duplicate_analysis(work_analysis, action=action):
        return False
    if tool_route_plan is None:
        return True
    return _matches_frozen_route(tool_route_plan, route_id=str(action["route_id"]))


def _exact_title(value: object) -> str | None:
    if (
        not isinstance(value, Sequence)
        or isinstance(value, (str, bytes))
        or len(value) != 1
        or not isinstance(value[0], Mapping)
    ):
        return None
    constraint = value[0]
    title = constraint.get("value")
    if (
        constraint.get("kind") != "RESOURCE"
        or constraint.get("field") != "title"
        or not isinstance(title, str)
        or not title
    ):
        return None
    return title


def _has_clean_duplicate_analysis(
    value: Mapping[str, object] | None, *, action: Mapping[str, object]
) -> bool:
    if (
        not isinstance(value, Mapping)
        or value.get("schema_version") != 2
        or value.get("action_necessity") != "REQUIRED"
        or value.get("ambiguities") != []
        or value.get("risks") != []
        or value.get("relations") != []
    ):
        return False
    evidence_refs = value.get("evidence_refs")
    action_refs = action.get("evidence_refs")
    return (
        isinstance(evidence_refs, list)
        and bool(evidence_refs)
        and all(isinstance(ref, str) and ref for ref in evidence_refs)
        and isinstance(action_refs, list)
        and set(evidence_refs).issubset(action_refs)
    )


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
        and route.get("resource_type") == "TASK"
        and route.get("connector_id") == "google_workspace"
        and route.get("effect") == "CREATE"
        and route.get("selected_tool_id") == "tasks_create_task"
    )


__all__ = ["is_exact_task_create_plan"]
