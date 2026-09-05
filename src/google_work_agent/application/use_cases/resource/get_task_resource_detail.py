"""Get Task detail only after opaque selection-handle validation."""

from dataclasses import dataclass

from google_work_agent.application.tool_registry.signed_tool_registry import SignedToolRegistry
from google_work_agent.application.use_cases.action.task_duplicate_policy import (
    normalize_scheduled_date,
)
from google_work_agent.application.use_cases.resource.resolve_selection_handle import (
    ResolveSelectionHandle,
    ResolveSelectionHandleQuery,
)
from google_work_agent.application.use_cases.resource.strip_resource_recovery_marker import (
    strip_resource_recovery_marker,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
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
    resource_id: str
    title: str
    task_status: str
    scheduled_date: str | None
    completed_at: str | None
    tasklist_id: str
    notes: str | None


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
                expected_resource_type="task",
                require_parent_match=False,
            )
        )
        if selected.resource_id != query.resource_id:
            raise ValueError("Task selection does not match requested resource")
        if selected.parent_resource_id is None:
            raise ValueError("Task selection requires task-list identity")
        result = self._connector_read.execute_read(
            self._registry.bind_required("google_workspace", "tasks_get_task", "READ"),
            {"task_list_id": selected.parent_resource_id, "task_id": selected.resource_id},
        )
        return _project_task_detail(result.output)


def _project_task_detail(output: dict[str, JsonValue]) -> GetTaskResourceDetailResult:
    item = output.get("item")
    if not isinstance(item, dict):
        raise _malformed_response()
    resource_id = _required_text(item, "resource_id")
    tasklist_id = _required_text(item, "parent_id")
    payload = item.get("payload")
    if not isinstance(payload, dict):
        raise _malformed_response()
    status = _required_text(payload, "status")
    task_status = {"needsAction": "incomplete", "completed": "completed"}.get(status)
    if task_status is None:
        raise _malformed_response()
    return GetTaskResourceDetailResult(
        resource_id=resource_id,
        title=_required_text(payload, "title"),
        task_status=task_status,
        scheduled_date=normalize_scheduled_date(payload.get("due")),
        completed_at=_optional_text(payload.get("completed")),
        tasklist_id=tasklist_id,
        notes=strip_resource_recovery_marker(_optional_text(payload.get("notes"))),
    )


def _required_text(values: dict[str, JsonValue], key: str) -> str:
    value = values.get(key)
    if not isinstance(value, str) or not value:
        raise _malformed_response()
    return value


def _optional_text(value: JsonValue) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _malformed_response()
    return value or None


def _malformed_response() -> ConnectorOperationFailure:
    return ConnectorOperationFailure(
        code=ConnectorFailureCode.MALFORMED_RESPONSE,
        detail_code="CONNECTOR_RESPONSE_MALFORMED",
    )


__all__ = [
    "GetTaskResourceDetailHandler",
    "GetTaskResourceDetailQuery",
    "GetTaskResourceDetailResult",
]
