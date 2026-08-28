"""Get Calendar detail only after opaque selection-handle validation."""

from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
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
    detail: dict[str, JsonValue]


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
                expected_resource_type="CALENDAR_EVENT",
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
        return GetCalendarResourceDetailResult(result.output)


__all__ = [
    "GetCalendarResourceDetailHandler",
    "GetCalendarResourceDetailQuery",
    "GetCalendarResourceDetailResult",
]
