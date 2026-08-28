"""Execute already-validated Retrieval reads through the connector port."""

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


class RetrievalReadExecutor:
    """Materialize connector requests from validated, cache-owned inputs only."""

    def __init__(
        self,
        *,
        connector_reader: ConnectorReadProjection,
        read_result_cache: RunScopedReadResultCache,
        now_ms: Callable[[], int],
        timezone_provider: Callable[[], str],
    ) -> None:
        self._connector_reader = connector_reader
        self._read_result_cache = read_result_cache
        self._now_ms = now_ms
        self._timezone_provider = timezone_provider

    def build_context(
        self, *, remaining_budget: dict[str, int], allowed_read_tool_ids: frozenset[str]
    ) -> RetrievalReadContext:
        return RetrievalReadContext(
            remaining_budget=remaining_budget,
            now_ms=self._now_ms(),
            timezone=self._timezone_provider(),
            allowed_read_tool_ids=allowed_read_tool_ids,
        )

    def execute_next_page(
        self,
        *,
        plan: SourceFetchPlanV1,
        run_id: str,
        route_id: str,
        query_hash: str,
        read_result_handle: str,
        context: RetrievalReadContext,
    ) -> NormalizedConnectorRead:
        """Resolve the opaque continuation and execute one validated page read."""
        page_token = self._read_result_cache.resolve_next_page(
            run_id=run_id,
            handle=read_result_handle,
            route_id=route_id,
            query_hash=query_hash,
        )
        return self._connector_reader.read(
            PlannedConnectorRead(
                plan=plan,
                selected_resources=(),
                prefer_selected_resources=False,
                remaining_budget=context.remaining_budget,
                now_ms=context.now_ms,
                timezone=context.timezone,
                allowed_read_tool_ids=context.allowed_read_tool_ids,
                page_token=page_token,
            )
        )

    def execute_search(
        self,
        *,
        plan: SourceFetchPlanV1,
        context: RetrievalReadContext,
    ) -> NormalizedConnectorRead:
        """Execute a validator-approved normalized SEARCH plan."""
        return self._connector_reader.read(
            PlannedConnectorRead(
                plan=plan,
                selected_resources=(),
                prefer_selected_resources=False,
                remaining_budget=context.remaining_budget,
                now_ms=context.now_ms,
                timezone=context.timezone,
                allowed_read_tool_ids=context.allowed_read_tool_ids,
            )
        )

    def execute_detail(
        self,
        *,
        plan: SourceFetchPlanV1,
        target: DetailTargetCacheEntry,
        context: RetrievalReadContext,
    ) -> NormalizedConnectorRead:
        if target.detail_tool_id not in context.allowed_read_tool_ids:
            raise PermissionError("detail tool is outside the frozen input route")
        return self._connector_reader.read(
            PlannedConnectorRead(
                plan=plan,
                selected_resources=(
                    SelectedResourceRef(
                        source=target.source,
                        resource_type=_connector_resource_type(target.resource_type),
                        resource_id=target.resource_id,
                        parent_resource_id=target.parent_resource_id,
                    ),
                ),
                prefer_selected_resources=True,
                remaining_budget=context.remaining_budget,
                now_ms=context.now_ms,
                timezone=context.timezone,
                allowed_read_tool_ids=context.allowed_read_tool_ids,
            )
        )


def _connector_resource_type(resource_type: str) -> str:
    return {
        "GMAIL_THREAD": "THREAD",
        "GMAIL_MESSAGE": "MESSAGE",
        "TASK": "TASK",
        "CALENDAR_EVENT": "EVENT",
    }[resource_type]
