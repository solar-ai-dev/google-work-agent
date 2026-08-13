"""Google Workspace implementation of connector write execution capabilities."""

from __future__ import annotations

from typing import Any, cast

from google_work_agent.application.ports import (
    ConnectorExecutionPort,
    ConnectorWriteRequest,
    PreparedConnectorWrite,
)
from google_work_agent.ports import GoogleWorkspaceGateway, ResourceSnapshot, ResourceType


class GoogleWorkspaceExecutionBackend(ConnectorExecutionPort):
    """Map stable Google tool ids to the existing Workspace gateway operations."""

    def __init__(self, *, gateway: GoogleWorkspaceGateway) -> None:
        self._gateway = gateway

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
            return self._gateway.send_gmail(
                draft_id=cast(str, arguments["draft_id"]),
                recovery_fingerprint=cast(str | None, arguments["recovery_fingerprint"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_delete_event":
            return self._gateway.delete_calendar_event(
                calendar_id=cast(str, arguments["calendar_id"]),
                event_id=cast(str, arguments["event_id"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_delete_task":
            return self._gateway.delete_task(
                task_list_id=cast(str, arguments["task_list_id"]),
                task_id=cast(str, arguments["task_id"]),
                claim_context=claim_context,
            )
        if tool_name == "gmail_create_draft":
            return self._gateway.create_gmail_draft(
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "gmail_update_draft":
            return self._gateway.update_gmail_draft(
                draft_id=cast(str, arguments["draft_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_create_task":
            return self._gateway.create_task(
                task_list_id=cast(str, arguments["task_list_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "tasks_update_task":
            return self._gateway.update_task(
                task_list_id=cast(str, arguments["task_list_id"]),
                task_id=cast(str, arguments["task_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_create_event":
            return self._gateway.create_calendar_event(
                calendar_id=cast(str, arguments["calendar_id"]),
                payload=cast(dict[str, Any], arguments["payload"]),
                claim_context=claim_context,
            )
        if tool_name == "calendar_update_event":
            return self._gateway.update_calendar_event(
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
            draft_id = str(arguments.get("draft_id") or _required_resource_id(fallback_resource_id))
            return self._gateway.get_gmail_draft(draft_id=draft_id)
        if tool_name == "gmail_send":
            return self._gateway.get_gmail_message(
                message_id=_required_resource_id(fallback_resource_id)
            )
        if tool_name in {"tasks_create_task", "tasks_update_task"}:
            return self._gateway.get_task(
                task_list_id=str(arguments["task_list_id"]),
                task_id=str(
                    arguments.get("task_id") or _required_resource_id(fallback_resource_id)
                ),
            )
        if tool_name in {"calendar_create_event", "calendar_update_event"}:
            return self._gateway.get_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                event_id=str(
                    arguments.get("event_id") or _required_resource_id(fallback_resource_id)
                ),
            )
        if tool_name == "calendar_delete_event":
            return self._gateway.get_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                event_id=str(arguments["event_id"]),
            )
        if tool_name == "tasks_delete_task":
            return self._gateway.get_task(
                task_list_id=str(arguments["task_list_id"]),
                task_id=str(arguments["task_id"]),
            )
        raise LookupError(f"unsupported verification tool: {tool_name}")

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        return self._gateway.search_by_recovery_fingerprint(
            resource_type=_recovery_resource_type_for_tool(tool_name),
            recovery_fingerprint=recovery_fingerprint,
        )


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


def _recovery_resource_type_for_tool(tool_name: str) -> ResourceType:
    if tool_name == "gmail_send":
        return ResourceType.GMAIL_MESSAGE
    if tool_name.startswith("gmail_"):
        return ResourceType.GMAIL_DRAFT
    if tool_name.startswith("tasks_"):
        return ResourceType.TASK
    if tool_name.startswith("calendar_"):
        return ResourceType.CALENDAR_EVENT
    raise LookupError(f"unsupported recovery tool: {tool_name}")


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
