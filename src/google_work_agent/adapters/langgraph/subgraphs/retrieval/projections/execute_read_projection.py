"""Typed Retrieval read projections at the Connector boundary."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import TypedDict, cast
from zoneinfo import ZoneInfo

from google_work_agent.application.agents.retrieval.contracts.query_plan import SourceFetchPlanV1
from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.tool_routing.contracts.tool_route_plan import (
    InputToolRouteV1,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadPort,
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.contracts.google_workspace import ResourceType
from google_work_agent.ports.connector.contracts.validated_connector_tool_binding import (
    ValidatedConnectorToolBindingV1,
)
from google_work_agent.ports.system.run_retrieval_cache_port import RunRetrievalCachePort


class ExecuteReadInput(TypedDict):
    plan: SourceFetchPlanV1
    run_id: str
    binding: ValidatedConnectorToolBindingV1
    tool_arguments: dict[str, JsonValue]
    connector_reader: ConnectorReadPort
    read_result_cache: RunRetrievalCachePort
    read_result_handle: str


def project_execute_read_input(state: Mapping[str, object]) -> ExecuteReadInput:
    inputs = state.get("operation_inputs")
    value = inputs.get("execute_read") if isinstance(inputs, Mapping) else None
    if not isinstance(value, Mapping):
        raise ValueError("missing typed input projection for retrieval.execute_read")
    return cast(ExecuteReadInput, dict(value))


def project_connector_call(
    plan: SourceFetchPlanV1,
    *,
    route: InputToolRouteV1,
    page_size: int,
    detail_resource: Mapping[str, object] | None = None,
) -> tuple[str, dict[str, JsonValue]]:
    """Lower one canonical plan without granting this projection route authority."""
    resource = plan["resource_type"]
    operation = plan["operation_kind"]
    has_resource_ref = any(
        constraint["kind"] == "RESOURCE_REF" for constraint in plan["effective_constraints"]
    )
    if operation == "DETAIL_FETCH" or has_resource_ref:
        if detail_resource is None:
            raise ValueError("detail read requires a validated resource")
        tool_id, arguments = _detail_call(resource, detail_resource)
    elif resource.startswith("GMAIL_") or resource == "EMAIL":
        tool_id = "gmail_search_threads"
        arguments = {
            "query": _gmail_query(plan),
            "page_size": page_size,
            "include_thread_metadata": True,
        }
    elif resource == "TASK_LIST":
        tool_id = "tasks_list_tasklists"
        arguments = {"page_size": page_size}
    elif resource == "TASK":
        tool_id = "tasks_list_tasks"
        arguments = {
            "task_list_id": _single_container(plan),
            "page_size": page_size,
            "show_completed": _includes_status(plan, "COMPLETED"),
            "show_hidden": False,
            "show_deleted": False,
        }
    elif resource == "CALENDAR":
        tool_id = "calendar_list_calendars"
        arguments = {"page_size": page_size}
    elif resource.startswith("CALENDAR"):
        if operation == "FREEBUSY" or resource == "CALENDAR_FREEBUSY":
            tool_id = "calendar_query_freebusy"
            start, end = _temporal_bounds(plan)
            arguments = {
                "calendar_ids": [_single_container(plan)],
                "time_min": start,
                "time_max": end,
            }
        else:
            tool_id = "calendar_list_events"
            arguments = {
                "calendar_id": _single_container(plan),
                "page_size": page_size,
                "single_events": True,
                "order_by": "startTime",
            }
            temporal = _optional_temporal_bounds(plan)
            if temporal is not None:
                arguments["time_min"], arguments["time_max"] = temporal
    else:
        raise ValueError(f"unsupported retrieval resource_type: {resource}")
    if tool_id not in route["allowed_read_tool_ids"]:
        raise PermissionError("read tool is outside the frozen input route")
    return tool_id, cast(dict[str, JsonValue], arguments)


def project_acquisition_result(
    results: list[tuple[SourceFetchPlanV1, ConnectorReadResultV1]],
    *,
    remaining_budget: dict[str, int],
) -> AcquisitionResultV1:
    summaries: list[dict[str, object]] = []
    handles: list[str] = []
    for plan, result in results:
        resources = _resources(plan, result)
        resource_handles = [cast(str, item["resource_handle"]) for item in resources]
        handles.extend(resource_handles)
        summaries.append(
            {
                "schema_version": 1,
                "route_id": plan["route_id"],
                "source": _source(plan["resource_type"]),
                "connector_id": plan["connector_id"],
                "status": "COMPLETE",
                "required": True,
                "error_code": None,
                "resource_count": len(resources),
                "resource_handles": resource_handles,
                "resources": resources,
            }
        )
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": handles,
        "source_summaries": summaries,
        "missing_slots": [],
        "remaining_budget": remaining_budget,
    }


def sanitize_acquisition_result(result: AcquisitionResultV1) -> AcquisitionResultV1:
    """Keep checkpointed acquisition state bounded to deterministic metadata."""
    return cast(
        AcquisitionResultV1,
        {
            **result,
            "resource_handles": list(result["resource_handles"]),
            "source_summaries": [
                _sanitize_source_summary(summary) for summary in result["source_summaries"]
            ],
            "missing_slots": list(result["missing_slots"]),
            "remaining_budget": dict(result["remaining_budget"]),
        },
    )


def _sanitize_source_summary(summary: Mapping[str, object]) -> dict[str, object]:
    resources = summary.get("resources")
    safe_resources: list[dict[str, object]] = []
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, Mapping):
                raise ValueError("acquisition resource summary must be a mapping")
            payload = resource.get("payload")
            raw_payload = payload if isinstance(payload, Mapping) else {}
            safe_resources.append(
                {
                    **{key: value for key, value in resource.items() if key != "payload"},
                    "payload": _bounded_payload(
                        str(resource.get("resource_type", "")), raw_payload
                    ),
                }
            )
    return {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in summary.items()
        if key != "resources"
    } | {"resources": safe_resources}


def _bounded_payload(resource_type: str, payload: Mapping[str, object]) -> dict[str, object]:
    scalar_fields: dict[str, tuple[str, ...]] = {
        ResourceType.GMAIL_THREAD.value: ("subject",),
        ResourceType.GMAIL_MESSAGE.value: ("subject",),
        ResourceType.GMAIL_DRAFT.value: ("subject",),
        ResourceType.TASK_LIST.value: ("title",),
        ResourceType.TASK.value: ("title", "status", "due"),
        ResourceType.CALENDAR.value: ("title",),
        ResourceType.CALENDAR_EVENT.value: (
            "title",
            "summary",
            "start",
            "end",
            "status",
            "event_kind",
            "transparency",
            "self_response_status",
        ),
    }
    if resource_type == ResourceType.CALENDAR_FREEBUSY.value:
        result: dict[str, object] = {
            key: value
            for key in ("time_min", "time_max")
            if (value := payload.get(key)) is None or isinstance(value, str)
        }
        intervals = payload.get("busy_intervals")
        if isinstance(intervals, list):
            result["busy_intervals"] = [
                {
                    key: value
                    for key in ("calendar_id", "start", "end", "transparency")
                    if isinstance((value := item.get(key)), str)
                }
                for item in intervals
                if isinstance(item, Mapping)
            ]
        return result
    allowed = scalar_fields.get(resource_type, ())
    return {
        key: value
        for key in allowed
        if (value := payload.get(key)) is None or isinstance(value, (str, int, float, bool))
    }


def find_detail_resource(
    candidate_ref: str, results: list[ConnectorReadResultV1]
) -> Mapping[str, object] | None:
    for result in results:
        raw_items = result.output.get("items", [])
        items = raw_items if isinstance(raw_items, list) else []
        item = result.output.get("item")
        if isinstance(item, Mapping):
            items = [*items, item]
        for raw in items:
            if not isinstance(raw, Mapping):
                continue
            if _resource_handle(raw) == candidate_ref:
                return raw
    return None


def _resources(plan: SourceFetchPlanV1, result: ConnectorReadResultV1) -> list[dict[str, object]]:
    raw_items = result.output.get("items", [])
    items = raw_items if isinstance(raw_items, list) else []
    item = result.output.get("item")
    if isinstance(item, Mapping):
        items = [*items, item]
    resources = [_resource(raw) for raw in items if isinstance(raw, Mapping)]
    calendars = result.output.get("calendars")
    if isinstance(calendars, list):
        start, end = _temporal_bounds(plan)
        for raw in calendars:
            if not isinstance(raw, Mapping):
                continue
            calendar_id = str(raw.get("calendar_id", ""))
            resources.append(
                {
                    "resource_handle": (
                        f"calendar_freebusy:{calendar_id}:{plan['query_identity_hash']}"
                    ),
                    "resource_type": "calendar_freebusy",
                    "resource_id": calendar_id,
                    "parent_id": None,
                    "version": plan["query_identity_hash"],
                    "related_resource_ids": [],
                    "connector_id": plan["connector_id"],
                    "payload": {
                        "time_min": start,
                        "time_max": end,
                        "busy_intervals": list(cast(list[object], raw.get("intervals", []))),
                    },
                }
            )
    return resources


def _resource(raw: Mapping[str, object]) -> dict[str, object]:
    return {
        "resource_handle": _resource_handle(raw),
        "resource_type": str(raw.get("resource_type", "")),
        "resource_id": str(raw.get("resource_id", "")),
        "parent_id": raw.get("parent_id"),
        "version": raw.get("version"),
        "related_resource_ids": list(cast(list[object], raw.get("related_resource_ids", []))),
        "connector_id": "google_workspace",
        "payload": dict(cast(Mapping[str, object], raw.get("payload", {}))),
    }


def _resource_handle(raw: Mapping[str, object]) -> str:
    return f"{raw.get('resource_type', '')}:{raw.get('resource_id', '')}"


def _detail_call(
    resource_type: str, resource: Mapping[str, object]
) -> tuple[str, dict[str, JsonValue]]:
    resource_id = str(resource.get("resource_id", ""))
    parent_id = resource.get("parent_id")
    if resource_type in {"EMAIL", "GMAIL_THREAD"}:
        return "gmail_get_thread", {"thread_id": resource_id}
    if resource_type == "GMAIL_MESSAGE":
        return "gmail_get_message", {"message_id": resource_id}
    if resource_type == "GMAIL_DRAFT":
        return "gmail_get_draft", {"draft_id": resource_id}
    if resource_type == "GMAIL_ATTACHMENT":
        if not isinstance(parent_id, str) or not parent_id:
            raise ValueError("Gmail attachment detail requires parent message id")
        return "gmail_get_attachment", {
            "message_id": parent_id,
            "attachment_id": resource_id,
        }
    if resource_type == "TASK":
        if not isinstance(parent_id, str) or not parent_id:
            raise ValueError("TASK detail requires parent task-list id")
        return "tasks_get_task", {"task_list_id": parent_id, "task_id": resource_id}
    if resource_type in {"CALENDAR", "CALENDAR_EVENT"}:
        if not isinstance(parent_id, str) or not parent_id:
            raise ValueError("Calendar detail requires parent calendar id")
        return "calendar_get_event", {"calendar_id": parent_id, "event_id": resource_id}
    raise ValueError(f"unsupported DETAIL_FETCH resource_type: {resource_type}")


def _single_container(plan: SourceFetchPlanV1) -> str:
    refs = [
        ref
        for constraint in plan["effective_constraints"]
        if constraint["kind"] == "CONTAINER_REF"
        for ref in constraint["container_refs"]
    ]
    if len(refs) != 1:
        raise ValueError("retrieval read requires exactly one validated container ref")
    return refs[0]


def _includes_status(plan: SourceFetchPlanV1, status: str) -> bool:
    return any(
        status in constraint["values"]
        for constraint in plan["effective_constraints"]
        if constraint["kind"] == "STATUS_SCOPE"
    )


def _gmail_query(plan: SourceFetchPlanV1) -> str:
    terms: list[str] = []
    for constraint in plan["effective_constraints"]:
        if constraint["kind"] == "KEYWORD":
            value = " ".join(constraint["terms"])
            terms.append(f'"{value}"' if constraint["match_mode"] == "PHRASE" else value)
        elif constraint["kind"] == "PARTICIPANT":
            prefixes = {"SENDER": "from:", "RECIPIENT": "to:", "ATTENDEE": "", "ANY": ""}
            values = [
                prefixes[item["role"]] + item["identity"] for item in constraint["participants"]
            ]
            joined = " ".join(values)
            terms.append("{" + joined + "}" if constraint["match_mode"] == "ANY" else joined)
        elif constraint["kind"] == "TEMPORAL_RANGE":
            if constraint["start_local"] is not None:
                terms.append("after:" + constraint["start_local"][:10].replace("-", "/"))
            if constraint["end_local"] is not None:
                terms.append("before:" + constraint["end_local"][:10].replace("-", "/"))
        elif constraint["kind"] == "RESOURCE_REF":
            terms.extend("rfc822msgid:" + item for item in constraint["resource_refs"])
        elif constraint["kind"] == "CONTAINER_REF":
            terms.extend("in:" + item for item in constraint["container_refs"])
        elif constraint["kind"] == "STATUS_SCOPE":
            mapping = {"DRAFT": "in:drafts", "SENT": "in:sent"}
            terms.extend(mapping[item] for item in constraint["values"] if item in mapping)
    if not terms:
        raise ValueError("EMAIL retrieval requires a translatable constraint")
    return " ".join(terms)


def _optional_temporal_bounds(plan: SourceFetchPlanV1) -> tuple[str, str] | None:
    values = [
        constraint
        for constraint in plan["effective_constraints"]
        if constraint["kind"] == "TEMPORAL_RANGE"
    ]
    return None if not values else _localized_bounds(values[0])


def _temporal_bounds(plan: SourceFetchPlanV1) -> tuple[str, str]:
    value = _optional_temporal_bounds(plan)
    if value is None:
        raise ValueError("calendar availability requires a temporal range")
    return value


def _localized_bounds(constraint: Mapping[str, object]) -> tuple[str, str]:
    start = constraint.get("start_local")
    end = constraint.get("end_local")
    timezone = constraint.get("timezone")
    if not all(isinstance(value, str) and value for value in (start, end, timezone)):
        raise ValueError("calendar temporal range requires both local bounds and timezone")
    zone = ZoneInfo(cast(str, timezone))
    return (
        datetime.fromisoformat(cast(str, start)).replace(tzinfo=zone).isoformat(),
        datetime.fromisoformat(cast(str, end)).replace(tzinfo=zone).isoformat(),
    )


def _source(resource_type: str) -> str:
    if resource_type.startswith("GMAIL") or resource_type == "EMAIL":
        return "GMAIL"
    if resource_type in {"TASK", "TASK_LIST"}:
        return "TASKS"
    return "CALENDAR"


__all__ = [
    "ExecuteReadInput",
    "find_detail_resource",
    "project_acquisition_result",
    "project_connector_call",
    "project_execute_read_input",
]
