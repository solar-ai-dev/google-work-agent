"""Google Workspace read execution and normalization for acquisition."""

from __future__ import annotations

from google_work_agent.application.ports import (
    ConnectorReadPort,
    ConnectorReadRequest,
    ConnectorReadResult,
)
from google_work_agent.application.workflows.handoff_contracts import (
    SourceFetchPlanV1,
)
from google_work_agent.application.workflows.temporal_query import resolve_temporal_query
from google_work_agent.ports import (
    FreeBusyCalendar,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
    SelectedResourceRef,
    TimeRange,
)


class GoogleWorkspaceConnectorReader(ConnectorReadPort):
    """Adapt the existing Google gateway to the acquisition read capability."""

    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    def read(self, request: ConnectorReadRequest) -> ConnectorReadResult:
        plan = request.plan
        remaining = request.remaining_budget
        if request.prefer_selected_resources:
            selected = _selected_snapshots(
                gateway=self._gateway,
                plan=plan,
                selected_resources=request.selected_resources,
                remaining=remaining,
            )
            if selected:
                return ConnectorReadResult(snapshots=tuple(selected))
        if plan["source"] == "GMAIL":
            snapshots = _acquire_gmail(
                gateway=self._gateway,
                plan=plan,
                remaining=remaining,
            )
            return ConnectorReadResult(snapshots=tuple(snapshots))
        if plan["source"] == "TASKS":
            snapshots = _acquire_tasks(
                gateway=self._gateway,
                plan=plan,
                remaining=remaining,
            )
            return ConnectorReadResult(snapshots=tuple(snapshots))
        snapshots, error_code = _acquire_calendar(
            gateway=self._gateway,
            plan=plan,
            remaining=remaining,
            now_ms=request.now_ms,
            timezone=request.timezone,
        )
        return ConnectorReadResult(snapshots=tuple(snapshots), error_code=error_code)


def _selected_snapshots(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    selected_resources: tuple[SelectedResourceRef, ...],
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    matching = [resource for resource in selected_resources if resource.source == plan["source"]]
    snapshots: list[ResourceSnapshot] = []
    for resource in matching:
        if resource.source == "GMAIL":
            snapshots.extend(
                _get_selected_gmail(gateway=gateway, resource=resource, remaining=remaining)
            )
        elif resource.source == "TASKS":
            snapshots.append(_get_selected_task(gateway=gateway, resource=resource))
        elif resource.source == "CALENDAR":
            snapshots.append(_get_selected_calendar(gateway=gateway, resource=resource))
    return snapshots


def _get_selected_gmail(
    *,
    gateway: GoogleWorkspaceGateway,
    resource: SelectedResourceRef,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    if resource.resource_type == "THREAD":
        thread_snapshot = gateway.get_gmail_thread(thread_id=resource.resource_id)
        remaining["details"] = max(0, remaining["details"] - 1)
        messages = _acquire_gmail_thread_messages(
            gateway=gateway,
            thread_snapshot=thread_snapshot,
            remaining=remaining,
        )
        return [thread_snapshot, *messages]
    if resource.resource_type == "MESSAGE":
        return [gateway.get_gmail_message(message_id=resource.resource_id)]
    raise ValueError(f"unsupported selected Gmail resource type: {resource.resource_type}")


def _get_selected_task(
    *, gateway: GoogleWorkspaceGateway, resource: SelectedResourceRef
) -> ResourceSnapshot:
    if resource.resource_type != "TASK":
        raise ValueError(f"unsupported selected Tasks resource type: {resource.resource_type}")
    if resource.parent_resource_id is None:
        raise ValueError("selected task requires parent_resource_id")
    return gateway.get_task(
        task_list_id=resource.parent_resource_id,
        task_id=resource.resource_id,
    )


def _get_selected_calendar(
    *, gateway: GoogleWorkspaceGateway, resource: SelectedResourceRef
) -> ResourceSnapshot:
    if resource.resource_type != "EVENT":
        raise ValueError(f"unsupported selected Calendar resource type: {resource.resource_type}")
    if resource.parent_resource_id is None:
        raise ValueError("selected calendar event requires parent_resource_id")
    return gateway.get_calendar_event(
        calendar_id=resource.parent_resource_id,
        event_id=resource.resource_id,
    )


def _acquire_gmail(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    query = _query_from_constraints(plan["constraints"])
    page = gateway.search_gmail_threads(
        query=query,
        page_token=None,
        page_size=plan["page_size"],
    )
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details: list[ResourceSnapshot] = []
    for thread_id in detail_ids:
        if remaining["details"] <= 0:
            break
        thread_snapshot = gateway.get_gmail_thread(thread_id=thread_id)
        remaining["details"] -= 1
        details.append(thread_snapshot)
        details.extend(
            _acquire_gmail_thread_messages(
                gateway=gateway,
                thread_snapshot=thread_snapshot,
                remaining=remaining,
            )
        )
    return details


def _acquire_gmail_thread_messages(
    *,
    gateway: GoogleWorkspaceGateway,
    thread_snapshot: ResourceSnapshot,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    message_ids = _string_list(thread_snapshot.payload.get("message_ids"))
    messages: list[ResourceSnapshot] = []
    for message_id in message_ids:
        if remaining["details"] <= 0:
            break
        try:
            message_snapshot = gateway.get_gmail_message(message_id=message_id)
        except GoogleWorkspaceGatewayError:
            continue
        remaining["details"] -= 1
        messages.append(message_snapshot)
    return messages


def _acquire_tasks(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
) -> list[ResourceSnapshot]:
    task_list_id = _constraint_string(plan["constraints"], "task_list_id")
    if task_list_id is None:
        lists_page = gateway.list_task_lists(page_token=None, page_size=1)
        remaining["pages"] -= 1
        if not lists_page.items:
            return []
        task_list_id = lists_page.items[0].resource_id
    page = gateway.list_tasks(
        task_list_id=task_list_id,
        page_token=None,
        page_size=plan["page_size"],
    )
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details = [
        gateway.get_task(task_list_id=task_list_id, task_id=task_id) for task_id in detail_ids
    ]
    remaining["details"] -= len(details)
    return details


def _acquire_calendar(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    remaining: dict[str, int],
    now_ms: int,
    timezone: str,
) -> tuple[list[ResourceSnapshot], str | None]:
    calendar_id = _constraint_string(plan["constraints"], "calendar_id")
    if calendar_id is None:
        calendars_page = gateway.list_calendars(page_token=None, page_size=1)
        remaining["pages"] -= 1
        if not calendars_page.items:
            return [], None
        calendar_id = calendars_page.items[0].resource_id
    page = gateway.list_calendar_events(
        calendar_id=calendar_id,
        page_token=None,
        page_size=plan["page_size"],
    )
    remaining["pages"] -= 1
    candidates = list(page.items[: plan["max_candidates"]])
    remaining["candidates"] -= len(candidates)
    detail_ids = [item.resource_id for item in candidates[: plan["detail_limit"]]]
    details = [
        gateway.get_calendar_event(calendar_id=calendar_id, event_id=event_id)
        for event_id in detail_ids
    ]
    remaining["details"] -= len(details)
    freebusy_snapshot, error_code = _maybe_query_freebusy(
        gateway=gateway,
        plan=plan,
        calendar_id=calendar_id,
        now_ms=now_ms,
        timezone=timezone,
        remaining=remaining,
    )
    if freebusy_snapshot is not None:
        details.append(freebusy_snapshot)
    return details, error_code


def _maybe_query_freebusy(
    *,
    gateway: GoogleWorkspaceGateway,
    plan: SourceFetchPlanV1,
    calendar_id: str,
    now_ms: int,
    timezone: str,
    remaining: dict[str, int],
) -> tuple[ResourceSnapshot | None, str | None]:
    if plan["calendar_read_mode"] != "EVENTS_AND_FREEBUSY":
        return None, None
    if remaining["details"] <= 0:
        return None, None
    temporal_query = plan["temporal_query"]
    if temporal_query is None:
        return None, "INVALID_TEMPORAL_QUERY"
    time_range = resolve_temporal_query(
        temporal_query=temporal_query,
        now_ms=now_ms,
        timezone=timezone,
    )
    if time_range is None:
        return None, "INVALID_TEMPORAL_QUERY"
    try:
        calendars = gateway.query_freebusy(calendar_ids=(calendar_id,), time_range=time_range)
    except GoogleWorkspaceGatewayError:
        return None, None
    remaining["details"] -= 1
    return (
        _freebusy_resource_snapshot(
            calendar_id=calendar_id,
            time_range=time_range,
            calendars=calendars,
        ),
        None,
    )


def _freebusy_resource_snapshot(
    *, calendar_id: str, time_range: TimeRange, calendars: tuple[FreeBusyCalendar, ...]
) -> ResourceSnapshot:
    intervals: list[dict[str, object]] = [
        {
            "calendar_id": calendar.calendar_id,
            "start": interval.start,
            "end": interval.end,
            "transparency": interval.transparency,
        }
        for calendar in calendars
        for interval in calendar.intervals
    ]
    return ResourceSnapshot(
        fixture_snapshot_id="",
        resource_type=ResourceType.CALENDAR_FREEBUSY,
        resource_id=f"freebusy-{calendar_id}-{time_range.start}-{time_range.end}",
        parent_id=calendar_id,
        related_resource_ids=(calendar_id,),
        version="",
        recovery_fingerprint=None,
        payload={
            "summary": _freebusy_summary(
                calendar_id=calendar_id,
                time_range=time_range,
                intervals=intervals,
            ),
            "calendar_id": calendar_id,
            "time_min": time_range.start,
            "time_max": time_range.end,
            "busy_intervals": intervals,
        },
    )


def _freebusy_summary(
    *, calendar_id: str, time_range: TimeRange, intervals: list[dict[str, object]]
) -> str:
    if not intervals:
        return (
            f"{calendar_id} has no busy intervals between {time_range.start} and {time_range.end}."
        )
    parts = [f"{item['start']}~{item['end']} ({item['transparency']})" for item in intervals]
    return (
        f"{calendar_id} busy intervals between {time_range.start} and {time_range.end}: "
        + "; ".join(parts)
    )


def _query_from_constraints(constraints: dict[str, object]) -> str:
    terms: list[str] = []
    for key in ("query", "topic", "person", "time"):
        value = constraints.get(key)
        if isinstance(value, str) and value.strip():
            terms.append(value.strip())
    return " ".join(terms)


def _constraint_string(constraints: dict[str, object], key: str) -> str | None:
    value = constraints.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]
