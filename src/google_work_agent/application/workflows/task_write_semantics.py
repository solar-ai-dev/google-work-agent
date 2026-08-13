"""Normalize product Task date semantics before an Action is persisted for approval."""

from __future__ import annotations

from copy import deepcopy
from datetime import date

_TASK_WRITE_TOOLS = frozenset({"tasks_create_task", "tasks_update_task"})
_UNSUPPORTED_TASK_TIME_FIELDS = frozenset(
    {"scheduled_time", "start_time", "end_time", "time_range"}
)


def normalize_task_write_arguments(
    tool_name: str, arguments: dict[str, object]
) -> dict[str, object]:
    """Make Task product semantics explicit while preserving legacy provider arguments.

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
