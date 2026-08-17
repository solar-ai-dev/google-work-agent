"""Planning-facing business argument schemas for registered P0 write Tools.

These schemas describe only the *approved business arguments* that Planning is
allowed to author.  ClaimContextV2, recovery fingerprints, execution attempt
identity, and other dispatch-only metadata are intentionally absent; those are
added later by deterministic execution code.

The actual Connector/MCP boundary remains the final authority and revalidates
arguments before dispatch.  This catalog is the narrow selected-Tool projection
used by the per-route Planning argument writer.
"""

from __future__ import annotations

from copy import deepcopy

from google_work_agent.application.workflows.planning_arguments import (
    PlanningArgumentBindingError,
)

JsonObject = dict[str, object]

_STRING = {"type": "string"}
_NON_EMPTY_STRING = {"type": "string", "minLength": 1}
_EMAIL_LIST = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
    "minItems": 1,
    "uniqueItems": True,
}
_OPTIONAL_EMAIL_LIST = {
    "type": "array",
    "items": {"type": "string", "minLength": 1},
    "uniqueItems": True,
}
_ATTACHMENT_DESCRIPTOR = {
    "type": "object",
    "additionalProperties": False,
    "required": ["staged_attachment_id", "filename", "mime_type", "size_bytes", "sha256"],
    "properties": {
        "staged_attachment_id": _NON_EMPTY_STRING,
        "filename": _NON_EMPTY_STRING,
        "mime_type": _NON_EMPTY_STRING,
        "size_bytes": {"type": "integer", "minimum": 0},
        "sha256": {"type": "string", "pattern": "^[0-9a-fA-F]{64}$"},
    },
}

_GMAIL_DRAFT_PAYLOAD = {
    "type": "object",
    "additionalProperties": False,
    "required": ["to", "subject", "body"],
    "properties": {
        "to": _EMAIL_LIST,
        "cc": _OPTIONAL_EMAIL_LIST,
        "bcc": _OPTIONAL_EMAIL_LIST,
        "subject": _STRING,
        "body": _STRING,
        "thread_id": _NON_EMPTY_STRING,
        "attachments": {
            "type": "array",
            "items": _ATTACHMENT_DESCRIPTOR,
            "maxItems": 10,
        },
    },
}

_TASK_CREATE_PAYLOAD = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title"],
    "properties": {
        "title": _NON_EMPTY_STRING,
        "notes": _STRING,
        "scheduled_date": {"type": "string", "format": "date"},
        "business_deadline": {"type": "string", "format": "date"},
        "status": {"type": "string", "enum": ["needsAction", "completed"]},
    },
}
_TASK_UPDATE_PAYLOAD = {
    **_TASK_CREATE_PAYLOAD,
    "required": [],
    "minProperties": 1,
}

_CALENDAR_CREATE_PAYLOAD = {
    "type": "object",
    "additionalProperties": False,
    "required": ["title", "start", "end"],
    "properties": {
        "title": _NON_EMPTY_STRING,
        "start": _NON_EMPTY_STRING,
        "end": _NON_EMPTY_STRING,
        "description": _STRING,
        "attendees": _OPTIONAL_EMAIL_LIST,
    },
}
_CALENDAR_UPDATE_PAYLOAD = {
    **_CALENDAR_CREATE_PAYLOAD,
    "required": [],
    "minProperties": 1,
}


def _object_schema(
    *,
    required: list[str],
    properties: dict[str, object],
) -> JsonObject:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": required,
        "properties": properties,
    }


_PLANNING_TOOL_SCHEMAS: dict[str, JsonObject] = {
    "gmail_create_draft": _object_schema(
        required=["payload"],
        properties={"payload": _GMAIL_DRAFT_PAYLOAD},
    ),
    "gmail_update_draft": _object_schema(
        required=["draft_id", "payload"],
        properties={
            "draft_id": _NON_EMPTY_STRING,
            "payload": {**_GMAIL_DRAFT_PAYLOAD, "required": [], "minProperties": 1},
        },
    ),
    "gmail_send": _object_schema(
        required=["draft_id"],
        properties={"draft_id": _NON_EMPTY_STRING},
    ),
    "tasks_create_task": _object_schema(
        required=["task_list_id", "payload"],
        properties={
            "task_list_id": _NON_EMPTY_STRING,
            "payload": _TASK_CREATE_PAYLOAD,
        },
    ),
    "tasks_update_task": _object_schema(
        required=["task_list_id", "task_id", "payload"],
        properties={
            "task_list_id": _NON_EMPTY_STRING,
            "task_id": _NON_EMPTY_STRING,
            "payload": _TASK_UPDATE_PAYLOAD,
        },
    ),
    "tasks_delete_task": _object_schema(
        required=["task_list_id", "task_id"],
        properties={
            "task_list_id": _NON_EMPTY_STRING,
            "task_id": _NON_EMPTY_STRING,
        },
    ),
    "calendar_create_event": _object_schema(
        required=["calendar_id", "payload"],
        properties={
            "calendar_id": _NON_EMPTY_STRING,
            "payload": _CALENDAR_CREATE_PAYLOAD,
        },
    ),
    "calendar_update_event": _object_schema(
        required=["calendar_id", "event_id", "payload"],
        properties={
            "calendar_id": _NON_EMPTY_STRING,
            "event_id": _NON_EMPTY_STRING,
            "payload": _CALENDAR_UPDATE_PAYLOAD,
        },
    ),
    "calendar_delete_event": _object_schema(
        required=["calendar_id", "event_id"],
        properties={
            "calendar_id": _NON_EMPTY_STRING,
            "event_id": _NON_EMPTY_STRING,
        },
    ),
}


def planning_tool_argument_schema(tool_id: str) -> JsonObject:
    """Return a defensive copy of one registered Planning write schema."""

    schema = _PLANNING_TOOL_SCHEMAS.get(tool_id)
    if schema is None:
        raise PlanningArgumentBindingError(
            f"no Planning business argument schema registered for selected tool: {tool_id}"
        )
    return deepcopy(schema)


def planning_write_tool_ids() -> frozenset[str]:
    return frozenset(_PLANNING_TOOL_SCHEMAS)


__all__ = ["planning_tool_argument_schema", "planning_write_tool_ids"]
