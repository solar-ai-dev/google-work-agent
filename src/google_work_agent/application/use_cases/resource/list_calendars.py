"""List calendar containers through ConnectorReadPort."""

from dataclasses import dataclass
from typing import cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue


@dataclass(frozen=True, slots=True)
class ListCalendarsQuery:
    page_token: str | None = None
    page_size: int = 50


@dataclass(frozen=True, slots=True)
class CalendarContainerListResponseV1:
    schema_version: int
    items: tuple[dict[str, JsonValue], ...]
    next_page_token: str | None


class ListCalendarsHandler:
    def __init__(self, *, connector_read: ConnectorReadPort, registry: SignedToolRegistry) -> None:
        self._connector_read = connector_read
        self._registry = registry

    def __call__(self, query: ListCalendarsQuery) -> CalendarContainerListResponseV1:
        if not 1 <= query.page_size <= 100:
            raise ValueError("page_size must be in 1..100")
        result = self._connector_read.execute_read(
            self._registry.bind_required("google_workspace", "calendar_list_calendars", "READ"),
            {"page_token": query.page_token, "page_size": query.page_size},
        )
        raw = result.output.get("items", [])
        if not isinstance(raw, list) or any(not isinstance(item, dict) for item in raw):
            raise ValueError("calendar-list result is malformed")
        return CalendarContainerListResponseV1(
            1, tuple(cast(list[dict[str, JsonValue]], raw)), result.next_page_token
        )


__all__ = ["CalendarContainerListResponseV1", "ListCalendarsHandler", "ListCalendarsQuery"]
