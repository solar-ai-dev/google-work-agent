"""Google Workspace connector execution-port composition.

Operation semantics live under adapters/connectors/google/<product>/<resource>/.
This module only preserves the application ConnectorWritePort composition
until integration rewires the shared composition root to the canonical package.
"""

from __future__ import annotations

from typing import Any, cast

from google_work_agent.adapters.connectors.google.calendar.events.create_event import (
    CreateEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.delete_event import (
    DeleteEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.get_event import (
    GetEventOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.search_events import (
    SearchEventsOperation,
)
from google_work_agent.adapters.connectors.google.calendar.events.update_event import (
    UpdateEventOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.create_draft import (
    CreateDraftOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.get_draft import (
    GetDraftOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.search_drafts import (
    SearchDraftsOperation,
)
from google_work_agent.adapters.connectors.google.gmail.drafts.update_draft import (
    UpdateDraftOperation,
)
from google_work_agent.adapters.connectors.google.gmail.messages.get_message import (
    GetMessageOperation,
)
from google_work_agent.adapters.connectors.google.gmail.messages.search_messages import (
    SearchMessagesOperation,
)
from google_work_agent.adapters.connectors.google.gmail.messages.send_message import (
    SendMessageOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasks.create_task import (
    CreateTaskOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasks.delete_task import (
    DeleteTaskOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasks.get_task import GetTaskOperation
from google_work_agent.adapters.connectors.google.tasks.tasks.search_tasks import (
    SearchTasksOperation,
)
from google_work_agent.adapters.connectors.google.tasks.tasks.update_task import (
    UpdateTaskOperation,
)
from google_work_agent.ports import GoogleWorkspaceGateway, ResourceSnapshot
from google_work_agent.ports.connector.connector_write_port import (
    ConnectorWritePort,
    ConnectorWriteRequest,
    PreparedConnectorWrite,
)


class McpConnectorWriteAdapter(ConnectorWritePort):
    """Compose stable tool ids onto canonical operation-per-file authorities."""

    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

    @property
    def last_request_id(self) -> str | None:
        return cast(str | None, getattr(self._gateway, "last_request_id", None))

    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedConnectorWrite:
        return PreparedConnectorWrite(
            tool_name=tool_name,
            arguments=_build_final_dispatch_arguments(
                tool_name,
                arguments,
                recovery_fingerprint=recovery_fingerprint,
            ),
        )

    def execute_write(self, request: ConnectorWriteRequest) -> ResourceSnapshot:
        tool_name = request.prepared.tool_name
        arguments = request.prepared.arguments
        claim_context = _prepare_claim_context(self._gateway, request)
        if tool_name == "gmail_send":
            return SendMessageOperation(gateway=self._gateway).execute(
                draft_id=cast(str, arguments["draft_id"]),
                recovery_fingerprint=cast(str | None, arguments["recovery_fingerprint"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_delete_event":
            return DeleteEventOperation(gateway=self._gateway).execute(
                calendar_id=cast(str, arguments["calendar_id"]),
                event_id=cast(str, arguments["event_id"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_delete_task":
            return DeleteTaskOperation(gateway=self._gateway).execute(
                task_list_id=cast(str, arguments["task_list_id"]),
                task_id=cast(str, arguments["task_id"]),
                claim_context=claim_context,
            )
        if tool_name == "gmail_create_draft":
            return CreateDraftOperation(gateway=self._gateway).execute(
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "gmail_update_draft":
            return UpdateDraftOperation(gateway=self._gateway).execute(
                draft_id=cast(str, arguments["draft_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_create_task":
            return CreateTaskOperation(gateway=self._gateway).execute(
                task_list_id=cast(str, arguments["task_list_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_update_task":
            return UpdateTaskOperation(gateway=self._gateway).execute(
                task_list_id=cast(str, arguments["task_list_id"]),
                task_id=cast(str, arguments["task_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_create_event":
            return CreateEventOperation(gateway=self._gateway).execute(
                calendar_id=cast(str, arguments["calendar_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_update_event":
            return UpdateEventOperation(gateway=self._gateway).execute(
                calendar_id=cast(str, arguments["calendar_id"]),
                event_id=cast(str, arguments["event_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        raise LookupError(f"unsupported write tool: {tool_name}")

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot:
        if tool_name in {"gmail_create_draft", "gmail_update_draft"}:
            return GetDraftOperation(gateway=self._gateway).execute(
                draft_id=str(
                    arguments.get("draft_id") or _required_resource_id(fallback_resource_id)
                )
            )
        if tool_name == "gmail_send":
            return GetMessageOperation(gateway=self._gateway).execute(
                message_id=_required_resource_id(fallback_resource_id)
            )
        if tool_name in {"tasks_create_task", "tasks_update_task", "tasks_delete_task"}:
            return GetTaskOperation(gateway=self._gateway).execute(
                task_list_id=str(arguments["task_list_id"]),
                task_id=str(
                    arguments.get("task_id") or _required_resource_id(fallback_resource_id)
                ),
            )
        if tool_name in {
            "calendar_create_event",
            "calendar_update_event",
            "calendar_delete_event",
        }:
            return GetEventOperation(gateway=self._gateway).execute(
                calendar_id=str(arguments["calendar_id"]),
                event_id=str(
                    arguments.get("event_id") or _required_resource_id(fallback_resource_id)
                ),
            )
        raise LookupError(f"unsupported verification tool: {tool_name}")

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        if tool_name == "gmail_send":
            return SearchMessagesOperation(gateway=self._gateway).execute(
                recovery_fingerprint=recovery_fingerprint
            )
        if tool_name.startswith("gmail_"):
            return SearchDraftsOperation(gateway=self._gateway).execute(
                recovery_fingerprint=recovery_fingerprint
            )
        if tool_name.startswith("tasks_"):
            return SearchTasksOperation(gateway=self._gateway).execute(
                recovery_fingerprint=recovery_fingerprint
            )
        if tool_name.startswith("calendar_"):
            return SearchEventsOperation(gateway=self._gateway).execute(
                recovery_fingerprint=recovery_fingerprint
            )
        raise LookupError(f"unsupported recovery tool: {tool_name}")


def _build_final_dispatch_arguments(
    tool_name: str,
    arguments: dict[str, object],
    *,
    recovery_fingerprint: str | None,
) -> dict[str, object]:
    if tool_name == "gmail_send":
        return {
            "draft_id": _required_argument_string(arguments, "draft_id"),
            "recovery_fingerprint": recovery_fingerprint,
        }
    if tool_name == "calendar_delete_event":
        return {
            "calendar_id": _required_argument_string(arguments, "calendar_id"),
            "event_id": _required_argument_string(arguments, "event_id"),
        }
    if tool_name == "tasks_delete_task":
        return {
            "task_list_id": _required_argument_string(arguments, "task_list_id"),
            "task_id": _required_argument_string(arguments, "task_id"),
        }
    payload = _dict_argument(arguments.get("payload"))
    payload_with_recovery = dict(payload)
    if recovery_fingerprint is not None and tool_name in {
        "gmail_create_draft",
        "tasks_create_task",
        "calendar_create_event",
    }:
        payload_with_recovery["recovery_fingerprint"] = recovery_fingerprint
    if tool_name == "gmail_create_draft":
        return {"payload": payload_with_recovery}
    if tool_name == "gmail_update_draft":
        return {"draft_id": str(arguments["draft_id"]), "payload": payload}
    if tool_name == "tasks_create_task":
        return {"task_list_id": str(arguments["task_list_id"]), "payload": payload_with_recovery}
    if tool_name == "tasks_update_task":
        return {
            "task_list_id": str(arguments["task_list_id"]),
            "task_id": str(arguments["task_id"]),
            "payload": payload,
        }
    if tool_name == "calendar_create_event":
        return {"calendar_id": str(arguments["calendar_id"]), "payload": payload_with_recovery}
    if tool_name == "calendar_update_event":
        return {
            "calendar_id": str(arguments["calendar_id"]),
            "event_id": str(arguments["event_id"]),
            "payload": payload,
        }
    raise LookupError(f"unsupported write tool: {tool_name}")


def _prepare_claim_context(
    gateway: GoogleWorkspaceGateway,
    request: ConnectorWriteRequest,
) -> dict[str, object] | None:
    prepare = getattr(gateway, "prepare_claim_context", None)
    if not callable(prepare):
        return None
    return cast(
        dict[str, object],
        prepare(
            claim_payload=request.claim_payload,
            tool_name=request.prepared.tool_name,
            approval_arguments_hash=request.approval_arguments_hash,
            execution_arguments_hash=request.execution_arguments_hash,
        ),
    )


def _required_argument_string(arguments: dict[str, object], name: str) -> str:
    value = arguments.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _required_resource_id(resource_id: str | None) -> str:
    if resource_id is None:
        raise LookupError("resource reference is required for verification")
    return resource_id


def _dict_argument(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("expected object argument")
    return cast(dict[str, object], value)
