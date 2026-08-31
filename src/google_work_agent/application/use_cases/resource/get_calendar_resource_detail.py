"""Get Calendar detail only after opaque selection-handle validation."""

from dataclasses import dataclass
from typing import cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue


@dataclass(frozen=True, slots=True)
class GetCalendarResourceDetailQuery:
    resource_id: str
    selection_handle: str
    session_digest: str
    account_id: str


@dataclass(frozen=True, slots=True)
class GetCalendarResourceDetailResult:
    resource_id: str
    title: str
    start: str
    end: str
    timezone: str
    calendar_id: str
    attendees: tuple[str, ...]
    location: str | None
    description: str | None


class GetCalendarResourceDetailHandler:
    def __init__(
        self,
        *,
        resolve_handle: ResolveSelectionHandle,
        connector_read: ConnectorReadPort,
        registry: SignedToolRegistry,
    ) -> None:
        self._resolve_handle = resolve_handle
        self._connector_read = connector_read
        self._registry = registry

    def __call__(self, query: GetCalendarResourceDetailQuery) -> GetCalendarResourceDetailResult:
        selected = self._resolve_handle(
            ResolveSelectionHandleQuery(
                query.selection_handle,
                query.session_digest,
                query.account_id,
                expected_connector_id="google_workspace",
                expected_resource_type="calendar_event",
                require_parent_match=False,
            )
        )
        if selected.resource_id != query.resource_id:
            raise ValueError("Calendar selection does not match requested resource")
        if selected.parent_resource_id is None:
            raise ValueError("Calendar selection requires calendar identity")
        result = self._connector_read.execute_read(
            self._registry.bind_required("google_workspace", "calendar_get_event", "READ"),
            {"calendar_id": selected.parent_resource_id, "event_id": selected.resource_id},
        )
        return _project_calendar_detail(result.output)


def _project_calendar_detail(output: dict[str, JsonValue]) -> GetCalendarResourceDetailResult:
    item = output.get("item")
    if not isinstance(item, dict):
        raise _malformed_response()
    payload = item.get("payload")
    if not isinstance(payload, dict):
        raise _malformed_response()
    attendees = payload.get("attendees", [])
    if not isinstance(attendees, list) or any(
        not isinstance(attendee, str) or not attendee for attendee in attendees
    ):
        raise _malformed_response()
    return GetCalendarResourceDetailResult(
        resource_id=_required_text(item, "resource_id"),
        title=_required_text(payload, "title"),
        start=_required_text(payload, "start"),
        end=_required_text(payload, "end"),
        timezone=_required_text(payload, "timezone"),
        calendar_id=_required_text(item, "parent_id"),
        attendees=tuple(cast(list[str], attendees)),
        location=_optional_text(payload.get("location")),
        description=_optional_text(payload.get("description")),
    )


def _required_text(values: dict[str, JsonValue], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise _malformed_response()
    return value


def _optional_text(value: JsonValue) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _malformed_response()
    return value or None


def _malformed_response() -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.MALFORMED_RESPONSE,
        detail_code="CONNECTOR_RESPONSE_MALFORMED",
    )


__all__ = [
    "GetCalendarResourceDetailHandler",
    "GetCalendarResourceDetailQuery",
    "GetCalendarResourceDetailResult",
]
