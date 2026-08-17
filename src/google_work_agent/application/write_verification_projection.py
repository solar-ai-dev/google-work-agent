"""Deterministic pre-write Expected projections for write verification.

Planning owns approved business arguments, not a fabricated provider snapshot.
This module converts those approved arguments into the bounded fields that a
post-write verification read can actually compare. Provider-generated ids,
versions, etags and timestamps are deliberately absent.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast


def build_expected_verification_projection(
    *,
    tool_name: str,
    arguments: Mapping[str, object],
) -> dict[str, object]:
    """Build the deterministic expected subset for one approved write."""

    args = dict(arguments)
    if tool_name == "gmail_send":
        return {
            "payload": {
                "sent": True,
                "draft_id": _required_string(args, "draft_id"),
            }
        }
    if tool_name in {"calendar_delete_event", "tasks_delete_task"}:
        # DELETE verification owns its explicit absent projection in
        # VerifyWriteActionService; no provider-generated Expected is needed.
        return {"absent": True}
    if tool_name in {"gmail_create_draft", "gmail_update_draft"}:
        payload = _mapping(args.get("payload"), "payload")
        expected_payload: dict[str, object] = {}
        if "subject" in payload:
            expected_payload["subject"] = _string(payload["subject"], "payload.subject")
        if "to" in payload:
            expected_payload["to"] = _email_header(payload["to"], "payload.to")
        if "thread_id" in payload:
            expected_payload["thread_id"] = _string(
                payload["thread_id"], "payload.thread_id"
            )
        # Current Gmail verification snapshot is metadata-only. Body/cc/bcc and
        # attachment-content verification are intentionally not claimed here;
        # those require a richer Connector verification snapshot before they
        # can become deterministic expected fields.
        return {"payload": expected_payload}
    if tool_name in {"tasks_create_task", "tasks_update_task"}:
        payload = _mapping(args.get("payload"), "payload")
        expected_payload = {}
        for name in ("title", "notes", "status"):
            if name in payload:
                expected_payload[name] = payload[name]
        if "scheduled_date" in payload:
            expected_payload["due"] = payload["scheduled_date"]
        return {"payload": expected_payload}
    if tool_name in {"calendar_create_event", "calendar_update_event"}:
        payload = _mapping(args.get("payload"), "payload")
        expected_payload = {}
        mapping = {
            "title": "title",
            "start": "start",
            "end": "end",
            "description": "description",
        }
        for argument_name, snapshot_name in mapping.items():
            if argument_name in payload:
                expected_payload[snapshot_name] = payload[argument_name]
        if "attendees" in payload:
            expected_payload["attendees"] = _string_list(
                payload["attendees"], "payload.attendees"
            )
        return {"payload": expected_payload}
    raise LookupError(f"unsupported write tool for expected verification: {tool_name}")


def calculate_verification_subset_diff(
    expected: object,
    actual: object,
    *,
    path: str = "$",
) -> list[dict[str, object]]:
    """Compare only fields declared by Expected; extra Actual fields are benign.

    Lists remain exact/order-sensitive because recipient/attendee ordering and
    cardinality are business-visible unless a Tool-specific normalizer changes
    them before this function is called.
    """

    if isinstance(expected, dict):
        if not isinstance(actual, dict):
            return [{"path": path, "expected": expected, "actual": actual}]
        expected_map = cast(dict[str, object], expected)
        actual_map = cast(dict[str, object], actual)
        diffs: list[dict[str, object]] = []
        for key in sorted(expected_map):
            if key not in actual_map:
                diffs.append(
                    {
                        "path": f"{path}.{key}",
                        "expected": expected_map[key],
                        "actual": "<missing>",
                    }
                )
                continue
            diffs.extend(
                calculate_verification_subset_diff(
                    expected_map[key],
                    actual_map[key],
                    path=f"{path}.{key}",
                )
            )
        return diffs
    if isinstance(expected, list):
        if not isinstance(actual, list) or expected != actual:
            return [{"path": path, "expected": expected, "actual": actual}]
        return []
    if expected != actual:
        return [{"path": path, "expected": expected, "actual": actual}]
    return []


def normalize_actual_verification_projection(
    *,
    tool_name: str,
    actual: Mapping[str, object],
) -> dict[str, object]:
    """Normalize provider-facing representation before subset comparison."""

    normalized = _deep_mapping_copy(actual)
    payload_value = normalized.get("payload")
    if not isinstance(payload_value, dict):
        return normalized
    payload = cast(dict[str, object], payload_value)
    if tool_name in {"tasks_create_task", "tasks_update_task"}:
        due = payload.get("due")
        if isinstance(due, str) and len(due) >= 10:
            payload["due"] = due[:10]
    if tool_name in {"calendar_create_event", "calendar_update_event"}:
        attendees = payload.get("attendees")
        if isinstance(attendees, list):
            payload["attendees"] = sorted(str(item) for item in attendees)
    return normalized


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return {str(key): item for key, item in value.items()}


def _required_string(value: Mapping[str, object], name: str) -> str:
    if name not in value:
        raise ValueError(f"{name} is required")
    return _string(value[name], name)


def _string(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be text")
    return value


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{path} must be a string list")
    return list(cast(list[str], value))


def _email_header(value: object, path: str) -> str:
    return ", ".join(_string_list(value, path))


def _deep_mapping_copy(value: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, item in value.items():
        if isinstance(item, Mapping):
            result[str(key)] = _deep_mapping_copy(cast(Mapping[str, object], item))
        elif isinstance(item, list):
            result[str(key)] = list(item)
        else:
            result[str(key)] = item
    return result


__all__ = [
    "build_expected_verification_projection",
    "calculate_verification_subset_diff",
    "normalize_actual_verification_projection",
]
