"""Project a current fixture into the Product connector resource contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import JsonValue

from evaluation.contracts.current_fixture_snapshot import CurrentFixtureSnapshotV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)


class FixtureProjectionError(ValueError):
    """Raised when a current fixture cannot satisfy the Product read contract."""


def project_product_resources(
    snapshot: CurrentFixtureSnapshotV1,
) -> tuple[ResourceSnapshot, ...]:
    resources = [
        *_gmail_resources(snapshot),
        *_task_resources(snapshot),
        *_calendar_resources(snapshot),
    ]
    identities = {(item.resource_type, item.resource_id) for item in resources}
    if len(identities) != len(resources):
        raise FixtureProjectionError("fixture contains duplicate Product resource identities")
    return tuple(sorted(resources, key=lambda item: (item.resource_type.value, item.resource_id)))


def _gmail_resources(snapshot: CurrentFixtureSnapshotV1) -> list[ResourceSnapshot]:
    resources: list[ResourceSnapshot] = []
    for thread in _object_rows(snapshot.gmail, "threads"):
        thread_id = _required_string(thread, "thread_id")
        subject = _required_string(thread, "subject")
        messages = _object_rows(thread, "messages")
        message_ids = [_required_string(message, "message_id") for message in messages]
        resources.append(
            _resource(
                snapshot,
                resource_type=ResourceType.GMAIL_THREAD,
                resource_id=thread_id,
                related_resource_ids=tuple(message_ids),
                payload={
                    "subject": subject,
                    "participants": cast(JsonValue, _string_rows(thread, "participants")),
                    "message_ids": cast(JsonValue, message_ids),
                    "body": "\n\n".join(_required_string(message, "body") for message in messages),
                },
            )
        )
        for message in messages:
            resources.append(
                _resource(
                    snapshot,
                    resource_type=ResourceType.GMAIL_MESSAGE,
                    resource_id=_required_string(message, "message_id"),
                    parent_id=thread_id,
                    related_resource_ids=(thread_id,),
                    version=_required_string(message, "sent_at"),
                    payload={
                        "from": _required_string(message, "sender"),
                        "to": cast(JsonValue, _string_rows(message, "to")),
                        "cc": cast(JsonValue, _string_rows(message, "cc")),
                        "subject": subject,
                        "received_at": _required_string(message, "sent_at"),
                        "body": _required_string(message, "body"),
                    },
                )
            )
    return resources


def _task_resources(snapshot: CurrentFixtureSnapshotV1) -> list[ResourceSnapshot]:
    resources = [
        _resource(
            snapshot,
            resource_type=ResourceType.TASK_LIST,
            resource_id=_required_string(tasklist, "tasklist_id"),
            payload=_payload(tasklist),
        )
        for tasklist in _object_rows(snapshot.tasks, "tasklists")
    ]
    resources.extend(
        _resource(
            snapshot,
            resource_type=ResourceType.TASK,
            resource_id=_required_string(task, "task_id"),
            parent_id=_required_string(task, "tasklist_id"),
            version=_optional_string(task, "updated_at") or snapshot.as_of,
            payload=_payload(task),
        )
        for task in _object_rows(snapshot.tasks, "tasks")
    )
    return resources


def _calendar_resources(snapshot: CurrentFixtureSnapshotV1) -> list[ResourceSnapshot]:
    resources = [
        _resource(
            snapshot,
            resource_type=ResourceType.CALENDAR,
            resource_id=_required_string(calendar, "calendar_id"),
            payload=_payload(calendar),
        )
        for calendar in _object_rows(snapshot.calendar, "calendars")
    ]
    resources.extend(
        _resource(
            snapshot,
            resource_type=ResourceType.CALENDAR_EVENT,
            resource_id=_required_string(event, "event_id"),
            parent_id=_required_string(event, "calendar_id"),
            version=_optional_string(event, "updated_at") or snapshot.as_of,
            payload=_payload(event),
        )
        for event in _object_rows(snapshot.calendar, "events")
    )
    return resources


def _resource(
    snapshot: CurrentFixtureSnapshotV1,
    *,
    resource_type: ResourceType,
    resource_id: str,
    payload: dict[str, JsonValue],
    parent_id: str | None = None,
    related_resource_ids: tuple[str, ...] = (),
    version: str | None = None,
) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=snapshot.fixture_snapshot_id,
        resource_type=resource_type,
        resource_id=resource_id,
        parent_id=parent_id,
        related_resource_ids=related_resource_ids,
        version=version or snapshot.as_of,
        recovery_fingerprint=None,
        payload=payload,
    )


def _object_rows(value: Mapping[str, object], field: str) -> list[dict[str, object]]:
    rows = value.get(field)
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise FixtureProjectionError(f"{field} must be an object array")
    return cast(list[dict[str, object]], rows)


def _required_string(value: Mapping[str, object], field: str) -> str:
    result = value.get(field)
    if not isinstance(result, str) or not result:
        raise FixtureProjectionError(f"{field} must be a non-empty string")
    return result


def _optional_string(value: Mapping[str, object], field: str) -> str | None:
    result = value.get(field)
    if result is None:
        return None
    if not isinstance(result, str) or not result:
        raise FixtureProjectionError(f"{field} must be a non-empty string when present")
    return result


def _string_rows(value: Mapping[str, object], field: str) -> list[str]:
    rows = value.get(field)
    if not isinstance(rows, list) or not all(isinstance(row, str) and row for row in rows):
        raise FixtureProjectionError(f"{field} must be a non-empty string array")
    return cast(list[str], rows)


def _payload(value: Mapping[str, object]) -> dict[str, JsonValue]:
    return cast(dict[str, JsonValue], dict(value))


__all__ = ["FixtureProjectionError", "project_product_resources"]
