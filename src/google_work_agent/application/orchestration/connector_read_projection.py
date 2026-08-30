"""Application-owned projection over the canonical ConnectorReadPort."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from google_work_agent.application.orchestration.connector_read_models import (
    NormalizedConnectorRead,
    PlannedConnectorRead,
)
from google_work_agent.application.orchestration.temporal_query import resolve_temporal_query
from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    FreeBusyInterval,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)


@dataclass(frozen=True, slots=True)
class ConnectorReadProjection:
    """Bind registered Tool identity before every legacy read projection."""

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

    def read(self, request: PlannedConnectorRead) -> NormalizedConnectorRead:
        plan = request.plan
        if request.prefer_selected_resources:
            selected = self._selected_snapshots(request)
            if selected:
                return NormalizedConnectorRead(snapshots=tuple(selected))
        if plan["source"] == "GMAIL":
            self._require_allowed(request, "gmail_search_threads")
            page = self.search_gmail_threads(
                query=_query(plan["constraints"]),
                page_token=request.page_token,
                page_size=plan["page_size"],
            )
            request.remaining_budget["pages"] -= 1
            candidates = list(page.items[: plan["max_candidates"]])
            request.remaining_budget["candidates"] -= len(candidates)
            details: list[ResourceSnapshot] = []
            for item in candidates[: plan["detail_limit"]]:
                if request.remaining_budget["details"] <= 0:
                    break
                self._require_allowed(request, "gmail_get_thread")
                thread = self.get_gmail_thread(thread_id=item.resource_id)
                request.remaining_budget["details"] -= 1
                details.append(thread)
                details.extend(self._gmail_thread_messages(request, thread))
            return NormalizedConnectorRead(tuple(details), next_page_token=page.next_page_token)
        if plan["source"] == "TASKS":
            task_list_id = _constraint(plan["constraints"], "task_list_id")
            if task_list_id is None:
                self._require_allowed(request, "tasks_list_tasklists")
                lists = self.list_task_lists(page_token=None, page_size=1)
                request.remaining_budget["pages"] -= 1
                if not lists.items:
                    return NormalizedConnectorRead(())
                task_list_id = lists.items[0].resource_id
            self._require_allowed(request, "tasks_list_tasks")
            page = self.list_tasks(
                task_list_id=task_list_id,
                page_token=request.page_token,
                page_size=plan["page_size"],
            )
            request.remaining_budget["pages"] -= 1
            candidates = list(page.items[: plan["max_candidates"]])
            request.remaining_budget["candidates"] -= len(candidates)
            details: list[ResourceSnapshot] = []
            for item in candidates[: plan["detail_limit"]]:
                self._require_allowed(request, "tasks_get_task")
                details.append(self.get_task(task_list_id=task_list_id, task_id=item.resource_id))
            request.remaining_budget["details"] -= len(details)
            return NormalizedConnectorRead(
                tuple(details),
                next_page_token=page.next_page_token,
            )
        calendar_id = _constraint(plan["constraints"], "calendar_id")
        if calendar_id is None:
            self._require_allowed(request, "calendar_list_calendars")
            calendars = self.list_calendars(page_token=None, page_size=1)
            request.remaining_budget["pages"] -= 1
            if not calendars.items:
                return NormalizedConnectorRead(())
            calendar_id = calendars.items[0].resource_id
        self._require_allowed(request, "calendar_list_events")
        page = self.list_calendar_events(
            calendar_id=calendar_id,
            page_token=request.page_token,
            page_size=plan["page_size"],
        )
        request.remaining_budget["pages"] -= 1
        candidates = list(page.items[: plan["max_candidates"]])
        request.remaining_budget["candidates"] -= len(candidates)
        details: list[ResourceSnapshot] = []
        for item in candidates[: plan["detail_limit"]]:
            self._require_allowed(request, "calendar_get_event")
            details.append(
                self.get_calendar_event(calendar_id=calendar_id, event_id=item.resource_id)
            )
        request.remaining_budget["details"] -= len(details)
        freebusy, error_code = self._calendar_freebusy(request, calendar_id)
        if freebusy is not None:
            details.append(freebusy)
        return NormalizedConnectorRead(
            tuple(details),
            error_code=error_code,
            next_page_token=page.next_page_token,
        )

    def _selected_snapshots(self, request: PlannedConnectorRead) -> list[ResourceSnapshot]:
        selected: list[ResourceSnapshot] = []
        for resource in request.selected_resources:
            if resource.source != request.plan["source"]:
                continue
            if resource.source == "GMAIL" and resource.resource_type == "THREAD":
                self._require_allowed(request, "gmail_get_thread")
                thread = self.get_gmail_thread(thread_id=resource.resource_id)
                request.remaining_budget["details"] = max(
                    0, request.remaining_budget["details"] - 1
                )
                selected.append(thread)
                selected.extend(self._gmail_thread_messages(request, thread))
            elif resource.source == "GMAIL" and resource.resource_type == "MESSAGE":
                self._require_allowed(request, "gmail_get_message")
                selected.append(self.get_gmail_message(message_id=resource.resource_id))
            elif resource.source == "GMAIL" and resource.resource_type == "DRAFT":
                self._require_allowed(request, "gmail_get_draft")
                selected.append(self.get_gmail_draft(draft_id=resource.resource_id))
            elif resource.source == "TASKS" and resource.parent_resource_id is not None:
                self._require_allowed(request, "tasks_get_task")
                selected.append(
                    self.get_task(
                        task_list_id=resource.parent_resource_id,
                        task_id=resource.resource_id,
                    )
                )
            elif resource.source == "CALENDAR" and resource.parent_resource_id is not None:
                self._require_allowed(request, "calendar_get_event")
                selected.append(
                    self.get_calendar_event(
                        calendar_id=resource.parent_resource_id,
                        event_id=resource.resource_id,
                    )
                )
            else:
                raise ValueError("selected resource cannot be materialized by its frozen route")
        return selected

    def _gmail_thread_messages(
        self, request: PlannedConnectorRead, thread: ResourceSnapshot
    ) -> list[ResourceSnapshot]:
        message_ids = thread.payload.get("message_ids")
        if not isinstance(message_ids, list):
            return []
        messages: list[ResourceSnapshot] = []
        for raw_message_id in message_ids:
            if request.remaining_budget["details"] <= 0:
                break
            try:
                self._require_allowed(request, "gmail_get_message")
                message = self.get_gmail_message(message_id=str(raw_message_id))
            except GoogleWorkspaceGatewayError:
                continue
            request.remaining_budget["details"] -= 1
            messages.append(message)
        return messages

    def _calendar_freebusy(
        self, request: PlannedConnectorRead, calendar_id: str
    ) -> tuple[ResourceSnapshot | None, str | None]:
        if request.plan["calendar_read_mode"] != "EVENTS_AND_FREEBUSY":
            return None, None
        if request.remaining_budget["details"] <= 0:
            return None, None
        temporal_query = request.plan["temporal_query"]
        if temporal_query is None:
            return None, "INVALID_TEMPORAL_QUERY"
        time_range = resolve_temporal_query(
            temporal_query=temporal_query,
            now_ms=request.now_ms,
            timezone=request.timezone,
        )
        if time_range is None:
            return None, "INVALID_TEMPORAL_QUERY"
        try:
            self._require_allowed(request, "calendar_query_freebusy")
            calendars = self.query_freebusy(calendar_ids=(calendar_id,), time_range=time_range)
        except GoogleWorkspaceGatewayError:
            return None, None
        request.remaining_budget["details"] -= 1
        return _freebusy_snapshot(calendar_id, time_range, calendars), None

    @staticmethod
    def _require_allowed(request: PlannedConnectorRead, *tool_ids: str) -> None:
        if request.allowed_read_tool_ids is None:
            return
        denied = sorted(set(tool_ids) - request.allowed_read_tool_ids)
        if denied:
            raise PermissionError(f"Connector READ outside frozen input route: {', '.join(denied)}")


def _freebusy_snapshot(
    calendar_id: str,
    time_range: TimeRange,
    calendars: tuple[FreeBusyCalendar, ...],
) -> ResourceSnapshot:
    intervals = [
        {
            "calendar_id": calendar.calendar_id,
            "start": interval.start,
            "end": interval.end,
            "transparency": interval.transparency,
        }
        for calendar in calendars
        for interval in calendar.intervals
    ]
    summary = (
        f"{calendar_id} has no busy intervals between {time_range.start} and {time_range.end}."
        if not intervals
        else (
            f"{calendar_id} busy intervals between {time_range.start} and {time_range.end}: "
            + "; ".join(
                f"{item['start']}~{item['end']} ({item['transparency']})" for item in intervals
            )
        )
    )
    return ResourceSnapshot(
        fixture_snapshot_id="",
        resource_type=ResourceType.CALENDAR_FREEBUSY,
        resource_id=f"freebusy-{calendar_id}-{time_range.start}-{time_range.end}",
        parent_id=calendar_id,
        related_resource_ids=(calendar_id,),
        version="",
        recovery_fingerprint=None,
        payload={
            "summary": summary,
            "calendar_id": calendar_id,
            "time_min": time_range.start,
            "time_max": time_range.end,
            "busy_intervals": intervals,
        },
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


def _constraint(constraints: dict[str, object], name: str) -> str | None:
    value = constraints.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _query(constraints: dict[str, object]) -> str:
    return " ".join(
        value.strip()
        for name in ("query", "topic", "person", "time")
        if isinstance((value := constraints.get(name)), str) and value.strip()
    )


__all__ = ["ConnectorReadProjection"]
