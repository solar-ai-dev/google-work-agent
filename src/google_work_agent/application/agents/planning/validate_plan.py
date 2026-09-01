"""Validate canonical Planning output without changing route/tool identity."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from datetime import date
from typing import cast

from google_work_agent.application.agents.planning.contracts.action_plan_draft import (
    ActionPlanDraftV2,
)

_WRITE_EFFECTS = frozenset({"CREATE", "UPDATE", "SEND", "DELETE"})


def validate_plan(
    value: object,
    *,
    output_routes: Sequence[Mapping[str, object]] | None = None,
    allowed_evidence_refs: set[str] | None = None,
) -> ActionPlanDraftV2:
    if not isinstance(value, Mapping):
        raise ValueError("ActionPlanDraftV2 must be an object")
    root = dict(value)
    if set(root) != {"schema_version", "meta", "actions"} or root["schema_version"] != 2:
        raise ValueError("invalid ActionPlanDraftV2 envelope")
    actions = root["actions"]
    if not isinstance(actions, list) or not actions:
        raise ValueError("plan requires actions")
    ids: set[str] = set()
    route_ids: set[str] = set()
    deps: dict[str, list[str]] = {}
    frozen_routes = tuple(output_routes or ())
    route_by_id = (
        {route.get("route_id"): route for route in frozen_routes}
        if output_routes is not None
        else None
    )
    if route_by_id is not None and (
        len(route_by_id) != len(frozen_routes)
        or not all(isinstance(key, str) and key for key in route_by_id)
    ):
        raise ValueError("frozen output routes must have unique route_id")
    for raw in actions:
        if not isinstance(raw, Mapping):
            raise ValueError("planned action must be an object")
        action = dict(raw)
        required = {
            "action_id",
            "route_id",
            "tool_id",
            "effect",
            "arguments",
            "evidence_refs",
            "depends_on_action_ids",
        }
        if set(action) != required:
            raise ValueError("planned action keys do not match contract")
        action_id = _text(action["action_id"], "action_id")
        route_id = _text(action["route_id"], "route_id")
        tool_id = _text(action["tool_id"], "tool_id")
        if action["effect"] not in _WRITE_EFFECTS:
            raise ValueError("invalid write effect")
        if action_id in ids or route_id in route_ids:
            raise ValueError("duplicate action_id or route_id")
        ids.add(action_id)
        route_ids.add(route_id)
        if not isinstance(action["arguments"], Mapping):
            raise ValueError("arguments must be an object")
        evidence_refs = _strings(action["evidence_refs"], "evidence_refs")
        if allowed_evidence_refs is not None and not set(evidence_refs).issubset(
            allowed_evidence_refs
        ):
            raise ValueError("planned action references unavailable evidence")
        if route_by_id is not None:
            route = route_by_id.get(route_id)
            if route is None:
                raise ValueError("planned action route escapes frozen output plan")
            if tool_id != route.get("selected_tool_id") or action["effect"] != route.get("effect"):
                raise ValueError("planned action changed frozen Tool/effect identity")
        deps[action_id] = _strings(action["depends_on_action_ids"], "depends_on_action_ids")
    if route_by_id is not None and route_ids != set(cast(dict[str, object], route_by_id)):
        raise ValueError("plan must contain exactly one action per frozen output route")
    for action_id, predecessors in deps.items():
        if action_id in predecessors or any(item not in ids for item in predecessors):
            raise ValueError("invalid action dependency")
    _acyclic(deps)
    return cast(ActionPlanDraftV2, root)


def _acyclic(edges: dict[str, list[str]]) -> None:
    active: set[str] = set()
    done: set[str] = set()

    def visit(node: str) -> None:
        if node in active:
            raise ValueError("action dependency cycle")
        if node in done:
            return
        active.add(node)
        for predecessor in edges[node]:
            visit(predecessor)
        active.remove(node)
        done.add(node)

    for node in edges:
        visit(node)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} contains duplicates")
    return list(value)


# Preserved task-write semantics now owned by this Planning validation operation.

_TASK_WRITE_TOOLS = frozenset({"tasks_create_task", "tasks_update_task"})
_UNSUPPORTED_TASK_TIME_FIELDS = frozenset(
    {"scheduled_time", "start_time", "end_time", "time_range"}
)


def normalize_task_write_arguments(
    tool_name: str, arguments: dict[str, object]
) -> dict[str, object]:
    """Make current Task product semantics explicit before provider translation.

    This runs while a plan is being validated, before its arguments are hashed
    and presented for approval.  ``due`` remains an MCP/Google boundary field;
    new product plans use ``scheduled_date`` and ``business_deadline``.
    """
    if tool_name not in _TASK_WRITE_TOOLS:
        return arguments

    normalized = deepcopy(arguments)
    payload_value = normalized.get("payload")
    if not isinstance(payload_value, dict):
        return normalized
    payload = payload_value
    unsupported_time_fields = _UNSUPPORTED_TASK_TIME_FIELDS.intersection(payload)
    if unsupported_time_fields:
        fields = ", ".join(sorted(unsupported_time_fields))
        raise ValueError(f"Task time range is not supported: {fields}")

    if "due" in payload:
        raise ValueError("Task due is a Provider-boundary field; use scheduled_date instead")
    _date_field(payload, "scheduled_date")

    business_deadline = _date_field(payload, "business_deadline")
    if "business_deadline" in payload and business_deadline is None:
        payload.pop("business_deadline", None)
    if business_deadline is not None:
        payload["notes"] = _append_business_deadline(payload.get("notes"), business_deadline)
    return normalized


def _date_field(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Task {key} must be an ISO date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"Task {key} must be an ISO date") from error
    return parsed.isoformat()


def _append_business_deadline(notes_value: object, deadline: str) -> str:
    if notes_value is None:
        notes = ""
    elif isinstance(notes_value, str):
        notes = notes_value.strip()
    else:
        raise ValueError("Task notes must be text")
    label = f"업무 마감: {_format_korean_date(deadline)}"
    if label in notes.splitlines():
        return notes
    return f"{notes}\n{label}" if notes else label


def _format_korean_date(value: str) -> str:
    parsed = date.fromisoformat(value)
    return f"{parsed.year}년 {parsed.month}월 {parsed.day}일"
