"""Get Task detail only after opaque selection-handle validation."""

from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
)
from google_work_agent.ports.connector.connector_read_port import ConnectorReadPort, JsonValue


@dataclass(frozen=True, slots=True)
class GetTaskResourceDetailQuery:
    resource_id: str
    selection_handle: str
    session_digest: str
    account_id: str


@dataclass(frozen=True, slots=True)
class GetTaskResourceDetailResult:
    detail: dict[str, JsonValue]


class GetTaskResourceDetailHandler:
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

    def __call__(self, query: GetTaskResourceDetailQuery) -> GetTaskResourceDetailResult:
        selected = self._resolve_handle(
            ResolveSelectionHandleQuery(
                query.selection_handle,
                query.session_digest,
                query.account_id,
                expected_connector_id="google_workspace",
                expected_resource_type="TASK",
                require_parent_match=False,
            )
        )
        if selected.resource_id != query.resource_id:
            raise ValueError("Task selection does not match requested resource")
        if selected.parent_resource_id is None:
            raise ValueError("Task selection requires task-list identity")
        result = self._connector_read.execute_read(
            self._registry.bind_required("google_workspace", "tasks_get_task", "READ"),
            {"tasklist_id": selected.parent_resource_id, "task_id": selected.resource_id},
        )
        return GetTaskResourceDetailResult(result.output)


__all__ = [
    "GetTaskResourceDetailHandler",
    "GetTaskResourceDetailQuery",
    "GetTaskResourceDetailResult",
]
