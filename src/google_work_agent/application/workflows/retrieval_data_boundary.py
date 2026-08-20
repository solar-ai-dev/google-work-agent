"""Checkpoint-safe boundary between provider reads and Retrieval local state.

The legacy acquisition materializer still owns read orchestration, but its raw
``ResourceSnapshot.payload`` projection is intercepted here before any
LangGraph node can return it.  Raw snapshots are moved into the existing
RunScopedReadResultCache; checkpointable acquisition state retains only
identity plus a small allowlisted compatibility projection required by
existing deterministic duplicate/conflict/feasibility consumers.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, cast

from google_work_agent.application.ports import ConnectorReadResult
from google_work_agent.application.workflows.api_acquisition import (
    ApiDiscoveryAcquisitionAgent,
    MaterializedRetrievalRead,
)
from google_work_agent.application.workflows.handoff_contracts import (
    AcquisitionResultV1,
    SourceFetchPlanV1,
)
from google_work_agent.application.workflows.retrieval_read_cache import (
    RunScopedReadResultCache,
)
from google_work_agent.application.workflows.tool_routing import ToolRoutePlanV2
from google_work_agent.ports import ResourceSnapshot, ResourceType, WorkflowStartRequest


class CheckpointSafeAcquisitionFacade:
    """One-way compatibility adapter that keeps raw provider content off state."""

    def __init__(
        self,
        *,
        agent: ApiDiscoveryAcquisitionAgent,
        read_result_cache: RunScopedReadResultCache,
    ) -> None:
        self._agent = agent
        self._read_result_cache = read_result_cache

    def __getattr__(self, name: str) -> Any:
        return getattr(self._agent, name)

    def acquire(self, **kwargs: Any) -> AcquisitionResultV1:
        request = cast(WorkflowStartRequest, kwargs["request"])
        provided_cache = kwargs.get("read_result_cache")
        if provided_cache is not None and provided_cache is not self._read_result_cache:
            raise ValueError("acquisition read cache authority mismatch")
        kwargs["read_result_cache"] = self._read_result_cache
        raw_result = self._agent.acquire(**kwargs)
        self._capture_legacy_snapshots(run_id=request.run_id, result=raw_result)
        return sanitize_acquisition_result(raw_result)

    def materialize_retrieval_read(
        self,
        *,
        plan: SourceFetchPlanV1,
        request: WorkflowStartRequest,
        tool_route_plan: ToolRoutePlanV2,
        read_result: ConnectorReadResult,
        read_result_cache: RunScopedReadResultCache,
        read_handle_factory: Callable[[], str],
    ) -> MaterializedRetrievalRead:
        if read_result_cache is not self._read_result_cache:
            raise ValueError("acquisition read cache authority mismatch")
        materialized = self._agent.materialize_retrieval_read(
            plan=plan,
            request=request,
            tool_route_plan=tool_route_plan,
            read_result=read_result,
            read_result_cache=read_result_cache,
            read_handle_factory=read_handle_factory,
        )
        if materialized.read_result_handle is not None:
            self._read_result_cache.attach_snapshots(
                run_id=request.run_id,
                handle=materialized.read_result_handle,
                snapshots=tuple(read_result.snapshots),
            )
        return replace(
            materialized,
            source_summary=sanitize_source_summary(materialized.source_summary),
        )

    def _capture_legacy_snapshots(
        self, *, run_id: str, result: AcquisitionResultV1
    ) -> None:
        for summary in result["source_summaries"]:
            resources = summary.get("resources")
            if not isinstance(resources, list) or not resources:
                continue
            snapshots = tuple(_snapshot_from_legacy_resource(item) for item in resources)
            handles = summary.get("resource_handles")
            if not isinstance(handles, list):
                raise ValueError("legacy acquisition summary is missing resource handles")
            self._read_result_cache.attach_snapshots_for_result(
                run_id=run_id,
                result_handles=tuple(str(item) for item in handles),
                snapshots=snapshots,
            )


def sanitize_acquisition_result(result: AcquisitionResultV1) -> AcquisitionResultV1:
    return cast(
        AcquisitionResultV1,
        {
            **result,
            "resource_handles": list(result["resource_handles"]),
            "source_summaries": [
                sanitize_source_summary(summary) for summary in result["source_summaries"]
            ],
            "missing_slots": list(result["missing_slots"]),
            "remaining_budget": dict(result["remaining_budget"]),
        },
    )


def sanitize_source_summary(summary: Mapping[str, object]) -> dict[str, object]:
    resources = summary.get("resources")
    safe_resources: list[dict[str, object]] = []
    if isinstance(resources, list):
        for resource in resources:
            if not isinstance(resource, Mapping):
                raise ValueError("acquisition resource summary must be a mapping")
            safe_resources.append(_safe_resource_projection(resource))
    return {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in summary.items()
        if key != "resources"
    } | {"resources": safe_resources}


def hydrate_acquisition_for_segmentation(
    *,
    run_id: str,
    result: AcquisitionResultV1,
    read_result_cache: RunScopedReadResultCache,
) -> AcquisitionResultV1:
    """Resolve raw content only for a synchronous segmentation call stack."""
    hydrated_summaries: list[dict[str, object]] = []
    for summary in result["source_summaries"]:
        hydrated_resources: list[dict[str, object]] = []
        resources = summary.get("resources")
        if isinstance(resources, list):
            for resource in resources:
                if not isinstance(resource, Mapping):
                    raise ValueError("acquisition resource summary must be a mapping")
                handle = resource.get("resource_handle")
                if not isinstance(handle, str) or not handle:
                    raise ValueError("acquisition resource summary is missing resource_handle")
                snapshot = read_result_cache.resolve_resource_snapshot(
                    run_id=run_id,
                    resource_handle=handle,
                )
                hydrated_resources.append(
                    {
                        **dict(resource),
                        "payload": dict(snapshot.payload),
                    }
                )
        hydrated_summaries.append({**summary, "resources": hydrated_resources})
    return cast(
        AcquisitionResultV1,
        {
            **result,
            "source_summaries": hydrated_summaries,
        },
    )


def _snapshot_from_legacy_resource(value: object) -> ResourceSnapshot:
    if not isinstance(value, Mapping):
        raise ValueError("legacy acquisition resource must be a mapping")
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        raise ValueError("legacy acquisition resource payload must be a mapping")
    related = value.get("related_resource_ids")
    return ResourceSnapshot(
        fixture_snapshot_id="run-retrieval-cache",
        resource_type=ResourceType(str(value["resource_type"])),
        resource_id=str(value["resource_id"]),
        parent_id=(str(value["parent_id"]) if value.get("parent_id") is not None else None),
        related_resource_ids=(
            tuple(str(item) for item in related) if isinstance(related, list) else ()
        ),
        version=str(value.get("version", "")),
        recovery_fingerprint=None,
        payload=dict(payload),
    )


def _safe_resource_projection(resource: Mapping[str, object]) -> dict[str, object]:
    payload = resource.get("payload")
    raw_payload = payload if isinstance(payload, Mapping) else {}
    return {
        key: (list(value) if isinstance(value, list) else value)
        for key, value in resource.items()
        if key != "payload"
    } | {"payload": _bounded_payload(str(resource.get("resource_type", "")), raw_payload)}


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
        return _bounded_freebusy_payload(payload)
    allowed = scalar_fields.get(resource_type, ())
    return {
        key: value
        for key in allowed
        if (value := payload.get(key)) is None or isinstance(value, (str, int, float, bool))
    }


def _bounded_freebusy_payload(payload: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in ("time_min", "time_max"):
        value = payload.get(key)
        if value is None or isinstance(value, str):
            result[key] = value
    intervals = payload.get("busy_intervals")
    if isinstance(intervals, list):
        bounded: list[dict[str, object]] = []
        for item in intervals:
            if not isinstance(item, Mapping):
                continue
            bounded.append(
                {
                    key: value
                    for key in ("calendar_id", "start", "end", "transparency")
                    if isinstance((value := item.get(key)), str)
                }
            )
        result["busy_intervals"] = bounded
    return result


__all__ = [
    "CheckpointSafeAcquisitionFacade",
    "hydrate_acquisition_for_segmentation",
    "sanitize_acquisition_result",
    "sanitize_source_summary",
]
