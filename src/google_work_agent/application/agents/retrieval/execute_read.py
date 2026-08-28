"""Canonical Retrieval deterministic operation: execute_read."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from google_work_agent.application.orchestration.connector_read_models import (
    NormalizedConnectorRead,
    PlannedConnectorRead,
)
from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.orchestration.handoff_contracts import SourceFetchPlanV1
from google_work_agent.application.orchestration.retrieval_read_cache import (
    DetailTargetCacheEntry,
    RunScopedReadResultCache,
)
from google_work_agent.ports.system.contracts.workflow_execution import SelectedResourceRef


@dataclass(frozen=True, slots=True)
class RetrievalReadContext:
    remaining_budget: dict[str, int]
    now_ms: int
    timezone: str
    allowed_read_tool_ids: frozenset[str]


def build_read_context(
    *,
    remaining_budget: dict[str, int],
    allowed_read_tool_ids: frozenset[str],
    now_ms: Callable[[], int],
    timezone_provider: Callable[[], str],
) -> RetrievalReadContext:
    return RetrievalReadContext(
        remaining_budget=remaining_budget,
        now_ms=now_ms(),
        timezone=timezone_provider(),
        allowed_read_tool_ids=allowed_read_tool_ids,
    )


def execute_read(
    *,
    plan: SourceFetchPlanV1,
    context: RetrievalReadContext,
    connector_reader: ConnectorReadProjection,
    read_result_cache: RunScopedReadResultCache | None = None,
    run_id: str | None = None,
    prior_query_hash: str | None = None,
    detail_target: DetailTargetCacheEntry | None = None,
) -> NormalizedConnectorRead:
    """Execute one validated read through ConnectorReadPort; never a Provider API."""
    operation = plan["operation_kind"]
    page_token: str | None = None
    selected_resources: tuple[SelectedResourceRef, ...] = ()
    prefer_selected = False

    if operation == "NEXT_PAGE":
        handle = plan["prior_read_result_handle"]
        if (
            read_result_cache is None
            or run_id is None
            or handle is None
            or prior_query_hash is None
        ):
            raise ValueError(
                "NEXT_PAGE requires run-scoped cache, run_id, prior handle, and prior query hash"
            )
        page_token = read_result_cache.resolve_next_page(
            run_id=run_id,
            handle=handle,
            route_id=plan["route_id"],
            query_hash=prior_query_hash,
        )
    elif operation == "DETAIL_FETCH":
        if detail_target is None:
            raise ValueError("DETAIL_FETCH requires a cache-resolved detail target")
        if detail_target.detail_tool_id not in context.allowed_read_tool_ids:
            raise PermissionError("detail tool is outside the frozen input route")
        selected_resources = (
            SelectedResourceRef(
                source=detail_target.source,
                resource_type=_connector_resource_type(detail_target.resource_type),
                resource_id=detail_target.resource_id,
                parent_resource_id=detail_target.parent_resource_id,
            ),
        )
        prefer_selected = True
    elif operation not in {"SEARCH", "FREEBUSY"}:
        raise ValueError(f"unsupported retrieval operation: {operation}")

    return connector_reader.read(
        PlannedConnectorRead(
            plan=plan,
            selected_resources=selected_resources,
            prefer_selected_resources=prefer_selected,
            remaining_budget=context.remaining_budget,
            now_ms=context.now_ms,
            timezone=context.timezone,
            allowed_read_tool_ids=context.allowed_read_tool_ids,
            page_token=page_token,
        )
    )


def _connector_resource_type(resource_type: str) -> str:
    return {
        "GMAIL_THREAD": "THREAD",
        "GMAIL_MESSAGE": "MESSAGE",
        "TASK": "TASK",
        "CALENDAR_EVENT": "EVENT",
    }[resource_type]
