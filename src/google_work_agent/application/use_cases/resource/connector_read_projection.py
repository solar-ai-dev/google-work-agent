"""Application-owned projection over the canonical ConnectorReadPort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    FreeBusyInterval,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)


@dataclass(frozen=True, slots=True)
class ConnectorReadProjection:
    """Bind registered Tool identity before every resource read projection."""

    connector_reader: ConnectorReadPort
    tool_registry: SignedToolRegistry
    connector_id: str = "google_workspace"

    def call(self, tool_id: str, arguments: dict[str, JsonValue]) -> dict[str, JsonValue]:
        binding = self.tool_registry.bind_required(self.connector_id, tool_id, "READ")
        return self.connector_reader.execute_read(binding, arguments).output

    def snapshot(self, tool_id: str, arguments: dict[str, JsonValue]) -> ResourceSnapshot:
        return _snapshot(cast(dict[str, object], self.call(tool_id, arguments)["item"]))

    def page(self, tool_id: str, arguments: dict[str, JsonValue]) -> ResourcePage:
        output = self.call(tool_id, arguments)
        return ResourcePage(
            items=tuple(
                _snapshot(cast(dict[str, object], item))
                for item in cast(list[object], output.get("items", []))
            ),
            next_page_token=_optional_string(output.get("next_page_token")),
        )

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
        include_thread_metadata: bool = True,
    ) -> ResourcePage:
        return self.page(
            "gmail_search_threads",
            {
                "query": query,
                "page_token": page_token,
                "page_size": page_size,
                "include_thread_metadata": include_thread_metadata,
            },
        )

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        return self.snapshot("gmail_get_thread", {"thread_id": thread_id})

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        return self.snapshot("gmail_get_message", {"message_id": message_id})

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        return self.snapshot("gmail_get_draft", {"draft_id": draft_id})

    def list_task_lists(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        return self.page(
            "tasks_list_tasklists",
            {"page_token": page_token, "page_size": page_size},
        )

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
        show_completed: bool = False,
        show_hidden: bool = False,
        show_deleted: bool = False,
    ) -> ResourcePage:
        return self.page(
            "tasks_list_tasks",
            {
                "task_list_id": task_list_id,
                "page_token": page_token,
                "page_size": page_size,
                "show_completed": show_completed,
                "show_hidden": show_hidden,
                "show_deleted": show_deleted,
            },
        )

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        return self.snapshot(
            "tasks_get_task",
            {"task_list_id": task_list_id, "task_id": task_id},
        )

    def list_calendars(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        return self.page(
            "calendar_list_calendars",
            {"page_token": page_token, "page_size": page_size},
        )

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str | None = None,
        time_max: str | None = None,
        single_events: bool = False,
        order_by: str | None = None,
    ) -> ResourcePage:
        arguments: dict[str, JsonValue] = {
            "calendar_id": calendar_id,
            "page_token": page_token,
            "page_size": page_size,
        }
        if time_min is not None:
            arguments["time_min"] = time_min
        if time_max is not None:
            arguments["time_max"] = time_max
        if single_events:
            arguments["single_events"] = True
        if order_by is not None:
            arguments["order_by"] = order_by
        return self.page("calendar_list_events", arguments)

    def query_freebusy(
        self,
        *,
        calendar_ids: tuple[str, ...],
        time_range: TimeRange,
    ) -> tuple[FreeBusyCalendar, ...]:
        output = self.call(
            "calendar_query_freebusy",
            {
                "calendar_ids": list(calendar_ids),
                "time_min": time_range.start,
                "time_max": time_range.end,
            },
        )
        return tuple(
            FreeBusyCalendar(
                calendar_id=str(item["calendar_id"]),
                intervals=tuple(
                    FreeBusyInterval(
                        start=str(interval["start"]),
                        end=str(interval["end"]),
                        transparency=str(interval["transparency"]),
                    )
                    for interval in cast(list[dict[str, object]], item["intervals"])
                ),
            )
            for item in cast(list[dict[str, object]], output["calendars"])
        )

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        return self.snapshot(
            "calendar_get_event",
            {"calendar_id": calendar_id, "event_id": event_id},
        )


def _snapshot(item: dict[str, object]) -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id=str(item["fixture_snapshot_id"]),
        resource_type=ResourceType(str(item["resource_type"])),
        resource_id=str(item["resource_id"]),
        parent_id=_optional_string(item.get("parent_id")),
        related_resource_ids=tuple(
            str(value) for value in cast(list[object], item["related_resource_ids"])
        ),
        version=str(item["version"]),
        recovery_fingerprint=_optional_string(item.get("recovery_fingerprint")),
        payload=cast(dict[str, object], item["payload"]),
    )


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["ConnectorReadProjection"]
