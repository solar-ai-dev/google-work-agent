"""Private connector-read phase of complete_read_action."""

from __future__ import annotations

from collections.abc import Callable
from json import dumps, loads

from google_work_agent.application.use_cases.action.read_contracts import (
    CompletedEvidence,
    CompletedResourceRef,
    ExecutedReadAction,
)
from google_work_agent.application.use_cases.action.read_persistence import (
    require_action,
    require_plan,
    require_run,
)
from google_work_agent.application.use_cases.resource.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.resource_ref.resource_ref_projection import (
    minimal_resource_metadata,
    snapshot_title,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.evidence.model import EvidenceOriginType
from google_work_agent.ports.connector.contracts.google_workspace import (
    FreeBusyCalendar,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


class _ReadExecution:
    """Execute one claimed read action outside of any SQLite transaction."""

    def __init__(
        self, *, unit_of_work_factory: Callable[[], UnitOfWork], gateway: ConnectorReadProjection
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._gateway = gateway
        self._dispatch = {
            "gmail_search_threads": self._execute_gmail_search_threads,
            "gmail_get_thread": self._execute_get_gmail_thread,
            "gmail_get_message": self._execute_get_gmail_message,
            "tasks_list_tasklists": self._execute_list_task_lists,
            "tasks_list_tasks": self._execute_list_tasks,
            "tasks_get_task": self._execute_get_task,
            "calendar_list_calendars": self._execute_list_calendars,
            "calendar_list_events": self._execute_list_calendar_events,
            "calendar_query_freebusy": self._execute_query_freebusy,
            "calendar_get_event": self._execute_get_calendar_event,
        }

    def __call__(self, *, action_id: str) -> ExecutedReadAction:
        with self._unit_of_work_factory() as unit_of_work:
            action = require_action(unit_of_work, action_id)
            plan = require_plan(unit_of_work, action.plan_id)
            run = require_run(unit_of_work, plan.run_id)
        if ActionStatusV1(action.status) is not ActionStatusV1.EXECUTING:
            raise RuntimeError(f"read action must be EXECUTING before external call: {action_id}")
        dispatch = self._dispatch.get(action.tool_name)
        if dispatch is None:
            raise RuntimeError(f"unsupported read tool dispatch: {action.tool_name}")
        return dispatch(run_id=run.id, arguments=loads(action.arguments_json))

    def _execute_gmail_search_threads(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.search_gmail_threads(
            query=str(arguments.get("query", "")),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_get_gmail_thread(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_gmail_thread(thread_id=str(arguments["thread_id"]))
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_get_gmail_message(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_gmail_message(message_id=str(arguments["message_id"]))
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_list_task_lists(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_task_lists(
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_list_tasks(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_tasks(
            task_list_id=str(arguments["task_list_id"]),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_get_task(self, *, run_id: str, arguments: dict[str, object]) -> ExecutedReadAction:
        result = self._gateway.get_task(
            task_list_id=str(arguments["task_list_id"]),
            task_id=str(arguments["task_id"]),
        )
        return _executed_from_snapshot(run_id=run_id, snapshot=result)

    def _execute_list_calendars(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_calendars(
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_list_calendar_events(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.list_calendar_events(
            calendar_id=str(arguments["calendar_id"]),
            page_token=_optional_str(arguments.get("page_token")),
            page_size=_int_argument(arguments.get("page_size"), default=50),
        )
        return _executed_from_resource_page(run_id=run_id, page=result)

    def _execute_query_freebusy(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        calendar_ids = _string_tuple_argument(arguments.get("calendar_ids"))
        time_range = TimeRange(
            start=str(arguments["time_min"]),
            end=str(arguments["time_max"]),
        )
        result = self._gateway.query_freebusy(
            calendar_ids=calendar_ids,
            time_range=time_range,
        )
        return _executed_from_freebusy(run_id=run_id, calendars=result)

    def _execute_get_calendar_event(
        self,
        *,
        run_id: str,
        arguments: dict[str, object],
    ) -> ExecutedReadAction:
        result = self._gateway.get_calendar_event(
            calendar_id=str(arguments["calendar_id"]),
            event_id=str(arguments["event_id"]),
        )
        return _executed_from_snapshot(run_id=run_id, snapshot=result)


def _executed_from_resource_page(run_id: str, page: ResourcePage) -> ExecutedReadAction:
    resources: list[CompletedResourceRef] = []
    evidence: list[CompletedEvidence] = []
    for snapshot in page.items:
        resource_ref, evidence_row = _projection_from_snapshot(run_id=run_id, snapshot=snapshot)
        resources.append(resource_ref)
        evidence.append(evidence_row)
    return ExecutedReadAction(
        output_json=dumps(
            {
                "result_kind": "RESOURCE_PAGE",
                "resource_ids": [item.resource_id for item in page.items],
                "next_page_token": page.next_page_token,
            },
            sort_keys=True,
        ),
        resource_refs=tuple(resources),
        evidence=tuple(evidence),
    )


def _executed_from_snapshot(run_id: str, snapshot: ResourceSnapshot) -> ExecutedReadAction:
    resource_ref, evidence = _projection_from_snapshot(run_id=run_id, snapshot=snapshot)
    return ExecutedReadAction(
        output_json=dumps(
            {"result_kind": "RESOURCE", "resource_id": snapshot.resource_id},
            sort_keys=True,
        ),
        resource_refs=(resource_ref,),
        evidence=(evidence,),
    )


def _executed_from_freebusy(
    run_id: str,
    calendars: tuple[FreeBusyCalendar, ...],
) -> ExecutedReadAction:
    resources: list[CompletedResourceRef] = []
    evidence: list[CompletedEvidence] = []
    for calendar in calendars:
        calendar_id = str(calendar.calendar_id)
        resources.append(
            CompletedResourceRef(
                id=f"resource-ref-{run_id}-{calendar_id}",
                resource_type=ResourceType.CALENDAR_FREEBUSY.value,
                resource_id=calendar_id,
                parent_resource_id=None,
                canonical_url=None,
                title=f"Calendar {calendar_id}",
                event_time_ms=None,
                version_token=None,
                metadata_json=dumps({"interval_count": len(calendar.intervals)}, sort_keys=True),
            )
        )
        evidence.append(
            CompletedEvidence(
                id=f"evidence-{run_id}-{calendar_id}",
                origin_type=EvidenceOriginType.DERIVED,
                kind="FREEBUSY",
                excerpt=f"Calendar {calendar_id} busy intervals: {len(calendar.intervals)}",
                locator_json=None,
            )
        )
    return ExecutedReadAction(
        output_json=dumps(
            {
                "result_kind": "FREEBUSY",
                "calendar_ids": [str(calendar.calendar_id) for calendar in calendars],
            },
            sort_keys=True,
        ),
        resource_refs=tuple(resources),
        evidence=tuple(evidence),
    )


def _projection_from_snapshot(
    *,
    run_id: str,
    snapshot: ResourceSnapshot,
) -> tuple[CompletedResourceRef, CompletedEvidence]:
    resource_type = _map_snapshot_resource_type(snapshot)
    title = snapshot_title(snapshot)
    excerpt = _snapshot_excerpt(snapshot)
    return (
        CompletedResourceRef(
            id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
            resource_type=resource_type,
            resource_id=snapshot.resource_id,
            parent_resource_id=snapshot.parent_id,
            canonical_url=_optional_str(snapshot.payload.get("canonical_url")),
            title=title,
            event_time_ms=None,
            version_token=snapshot.version,
            metadata_json=dumps(minimal_resource_metadata(snapshot), sort_keys=True),
        ),
        CompletedEvidence(
            id=f"evidence-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
            origin_type=EvidenceOriginType.GOOGLE_RESOURCE,
            kind=snapshot.resource_type.value.upper(),
            excerpt=excerpt,
            locator_json=None,
            resource_ref_id=f"resource-ref-{run_id}-{snapshot.resource_type.value}-{snapshot.resource_id}",
        ),
    )


def _map_snapshot_resource_type(snapshot: ResourceSnapshot) -> str:
    mapping = {
        "gmail_thread": ResourceType.GMAIL_THREAD.value,
        "gmail_message": ResourceType.GMAIL_MESSAGE.value,
        "gmail_draft": ResourceType.GMAIL_DRAFT.value,
        "task_list": ResourceType.TASK_LIST.value,
        "task": ResourceType.TASK.value,
        "calendar": ResourceType.CALENDAR.value,
        "calendar_event": ResourceType.CALENDAR_EVENT.value,
        "calendar_freebusy": ResourceType.CALENDAR_FREEBUSY.value,
    }
    return mapping[snapshot.resource_type.value]


def _snapshot_excerpt(snapshot: ResourceSnapshot) -> str:
    if snapshot.resource_type.value == "gmail_message":
        subject = _optional_str(snapshot.payload.get("subject"))
        sender = _optional_str(snapshot.payload.get("from"))
        return f"Message from {sender or 'unknown'}{f' about {subject}' if subject else ''}"[:512]
    if snapshot.resource_type.value == "gmail_thread":
        return str(
            snapshot.payload.get("snippet", snapshot.payload.get("subject", snapshot.resource_id))
        )[:512]
    return str(
        snapshot.payload.get("title", snapshot.payload.get("subject", snapshot.resource_id))
    )[:512]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _int_argument(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        return int(value)
    raise TypeError("expected int-like argument")


def _string_tuple_argument(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (list, tuple)):
        raise ValueError("expected a list or tuple of strings")
    return tuple(str(item) for item in value)
