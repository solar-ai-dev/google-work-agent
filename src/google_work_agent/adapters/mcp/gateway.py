"""Google Workspace gateway implemented over MCP tools."""

from __future__ import annotations

from base64 import urlsafe_b64decode
from json import dumps
from typing import Any, cast

from google_work_agent.ports import (
    FreeBusyCalendar,
    FreeBusyInterval,
    GmailAttachmentBytes,
    GmailAttachmentMetadata,
    GmailThreadDetail,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    MCPTransport,
    MCPTransportError,
    MCPTransportErrorCode,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)


class MCPGmailAttachmentGateway:
    """Gmail attachment READ gateway implemented over the MCP transport.

    Kept separate from ``MCPGoogleWorkspaceGateway`` deliberately: attachment
    bytes have no place moving through the write/verification port that the
    rest of the application depends on, so this stays a narrow, standalone
    adapter used only by the attachment download route.
    """

    def __init__(self, *, transport: MCPTransport) -> None:
        self._transport = transport

    def get_gmail_attachment(self, *, message_id: str, attachment_id: str) -> GmailAttachmentBytes:
        try:
            payload = self._transport.call_tool(
                tool_name="gmail_get_attachment",
                arguments={"message_id": message_id, "attachment_id": attachment_id},
            ).payload
        except MCPTransportError as error:
            raise _google_error_from_transport(error) from error
        raw_value = str(payload["data_base64url"])
        padding = "=" * (-len(raw_value) % 4)
        return GmailAttachmentBytes(
            message_id=str(payload["message_id"]),
            attachment_id=str(payload["attachment_id"]),
            size_bytes=int(cast(int, payload["size_bytes"])),
            sha256=str(payload["sha256"]),
            data=urlsafe_b64decode(raw_value + padding),
        )


class MCPGmailUiReadGateway:
    """UI-only Gmail detail gateway kept outside the Agent tool port."""

    def __init__(self, *, transport: MCPTransport) -> None:
        self._transport = transport

    def get_thread_detail(self, *, thread_id: str) -> GmailThreadDetail:
        try:
            payload = self._transport.call_tool(
                tool_name="gmail_get_ui_thread_detail",
                arguments={"thread_id": thread_id},
            ).payload
        except MCPTransportError as error:
            raise _google_error_from_transport(error) from error
        values = cast(dict[str, object], payload)
        attachments = tuple(
            GmailAttachmentMetadata(
                message_id=str(item["message_id"]),
                attachment_id=str(item["attachment_id"]),
                filename=str(item["filename"]),
                mime_type=str(item["mime_type"]),
                size_bytes=(
                    int(cast(int, item["size_bytes"]))
                    if isinstance(item.get("size_bytes"), int)
                    else None
                ),
            )
            for item in cast(list[dict[str, object]], values.get("attachments", []))
        )
        return GmailThreadDetail(
            thread_id=str(values["thread_id"]),
            message_id=str(values["message_id"]),
            sender_name=_optional_string(values.get("sender_name")),
            sender_email=_optional_string(values.get("sender_email")),
            recipients=tuple(
                str(item) for item in cast(list[object], values.get("recipients", []))
            ),
            cc=tuple(str(item) for item in cast(list[object], values.get("cc", []))),
            subject=_optional_string(values.get("subject")),
            received_at=_optional_string(values.get("received_at")),
            body=_optional_string(values.get("body")),
            attachments=attachments,
            version=str(values.get("version", "")),
        )


class MCPGoogleWorkspaceGateway(GoogleWorkspaceGateway):
    def __init__(self, *, transport: MCPTransport) -> None:
        self._transport = transport

    def prepare_claim_context(
        self,
        *,
        claim_payload: dict[str, object],
        tool_name: str,
        approval_arguments_hash: str,
        execution_arguments_hash: str,
    ) -> dict[str, object]:
        """Build and sign the R8.4 ClaimContextV2 envelope for one MCP write call.

        ``approval_arguments_hash`` binds the business arguments the user
        approved; ``execution_arguments_hash`` binds the actual final
        arguments about to be dispatched (including any server-generated
        metadata). MCP independently re-derives the latter from the
        arguments it actually receives, so the two hashes must be kept
        separate rather than collapsed into one value.
        """

        transport = cast(Any, self._transport)
        process_instance_id = cast(str | None, getattr(transport, "process_instance_id", None))
        if process_instance_id is None:
            raise RuntimeError("mcp process instance id is unavailable")
        payload = {
            "claim_version": 2,
            "action_id": str(claim_payload["action_id"]),
            "approval_id": str(claim_payload["approval_id"]),
            "execution_attempt_id": str(claim_payload["attempt_id"]),
            "tool_name": tool_name,
            "approval_arguments_hash": approval_arguments_hash,
            "execution_arguments_hash": execution_arguments_hash,
            "service_instance_id": str(claim_payload["service_instance_id"]),
            "mcp_process_instance_id": process_instance_id,
            "issued_at_ms": int(str(claim_payload["issued_at_ms"])),
            "expires_at_ms": int(str(claim_payload["expires_at_ms"])),
            "nonce": str(claim_payload["nonce"]),
        }
        payload["signature"] = str(transport.sign_claim_context(payload))
        return payload

    def search_gmail_threads(
        self,
        *,
        query: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._page(
            "gmail_search_threads",
            {"query": query, "page_token": page_token, "page_size": page_size},
        )

    def get_gmail_thread(self, *, thread_id: str) -> ResourceSnapshot:
        return self._snapshot("gmail_get_thread", {"thread_id": thread_id})

    def get_gmail_message(self, *, message_id: str) -> ResourceSnapshot:
        return self._snapshot("gmail_get_message", {"message_id": message_id})

    def create_gmail_draft(
        self,
        *,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "gmail_create_draft",
            {"payload": payload, "claim_context": claim_context},
        )

    def update_gmail_draft(
        self,
        *,
        draft_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "gmail_update_draft",
            {"draft_id": draft_id, "payload": payload, "claim_context": claim_context},
        )

    def get_gmail_draft(self, *, draft_id: str) -> ResourceSnapshot:
        return self._snapshot("gmail_get_draft", {"draft_id": draft_id})

    def send_gmail(
        self,
        *,
        draft_id: str,
        recovery_fingerprint: str | None,
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "gmail_send",
            {
                "draft_id": draft_id,
                "recovery_fingerprint": recovery_fingerprint,
                "claim_context": claim_context,
            },
        )

    def list_task_lists(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        return self._page(
            "tasks_list_tasklists",
            {"page_token": page_token, "page_size": page_size},
        )

    def list_tasks(
        self,
        *,
        task_list_id: str,
        page_token: str | None,
        page_size: int,
    ) -> ResourcePage:
        return self._page(
            "tasks_list_tasks",
            {"task_list_id": task_list_id, "page_token": page_token, "page_size": page_size},
        )

    def get_task(self, *, task_list_id: str, task_id: str) -> ResourceSnapshot:
        return self._snapshot("tasks_get_task", {"task_list_id": task_list_id, "task_id": task_id})

    def create_task(
        self,
        *,
        task_list_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "tasks_create_task",
            {
                "task_list_id": task_list_id,
                "payload": payload,
                "claim_context": claim_context,
            },
        )

    def update_task(
        self,
        *,
        task_list_id: str,
        task_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "tasks_update_task",
            {
                "task_list_id": task_list_id,
                "task_id": task_id,
                "payload": payload,
                "claim_context": claim_context,
            },
        )

    def delete_task(
        self,
        *,
        task_list_id: str,
        task_id: str,
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "tasks_delete_task",
            {
                "task_list_id": task_list_id,
                "task_id": task_id,
                "claim_context": claim_context,
            },
        )

    def list_calendars(self, *, page_token: str | None, page_size: int) -> ResourcePage:
        return self._page(
            "calendar_list_calendars",
            {"page_token": page_token, "page_size": page_size},
        )

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        page_token: str | None,
        page_size: int,
        time_min: str | None = None,
        time_max: str | None = None,
        single_events: bool = False,
        order_by: str | None = None,
    ) -> ResourcePage:
        arguments: dict[str, object] = {
            "calendar_id": calendar_id,
            "page_token": page_token,
            "page_size": page_size,
        }
        if time_min is not None:
            arguments["time_min"] = time_min
        if time_max is not None:
            arguments["time_max"] = time_max
        if order_by is not None:
            arguments["order_by"] = order_by
        if single_events:
            arguments["single_events"] = True
        return self._page(
            "calendar_list_events",
            arguments,
        )

    def query_freebusy(
        self,
        *,
        calendar_ids: tuple[str, ...],
        time_range: TimeRange,
    ) -> tuple[FreeBusyCalendar, ...]:
        payload = self._call(
            "calendar_query_freebusy",
            {
                "calendar_ids": list(calendar_ids),
                "time_min": time_range.start,
                "time_max": time_range.end,
            },
        )
        results: list[FreeBusyCalendar] = []
        for item in cast(list[dict[str, object]], payload["calendars"]):
            intervals = tuple(
                FreeBusyInterval(
                    start=str(interval["start"]),
                    end=str(interval["end"]),
                    transparency=str(interval["transparency"]),
                )
                for interval in cast(list[dict[str, object]], item["intervals"])
            )
            results.append(
                FreeBusyCalendar(calendar_id=str(item["calendar_id"]), intervals=intervals)
            )
        return tuple(results)

    def get_calendar_event(self, *, calendar_id: str, event_id: str) -> ResourceSnapshot:
        return self._snapshot(
            "calendar_get_event",
            {"calendar_id": calendar_id, "event_id": event_id},
        )

    def create_calendar_event(
        self,
        *,
        calendar_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "calendar_create_event",
            {
                "calendar_id": calendar_id,
                "payload": payload,
                "claim_context": claim_context,
            },
        )

    def update_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        payload: dict[str, Any],
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "calendar_update_event",
            {
                "calendar_id": calendar_id,
                "event_id": event_id,
                "payload": payload,
                "claim_context": claim_context,
            },
        )

    def delete_calendar_event(
        self,
        *,
        calendar_id: str,
        event_id: str,
        claim_context: dict[str, Any] | None = None,
    ) -> ResourceSnapshot:
        return self._snapshot(
            "calendar_delete_event",
            {
                "calendar_id": calendar_id,
                "event_id": event_id,
                "claim_context": claim_context,
            },
        )

    def search_by_recovery_fingerprint(
        self,
        *,
        resource_type: ResourceType,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        payload = self._call(
            "search_by_recovery_fingerprint",
            {
                "resource_type": resource_type.value,
                "recovery_fingerprint": recovery_fingerprint,
            },
        )
        return tuple(
            self._resource_snapshot(item)
            for item in cast(list[dict[str, object]], payload["items"])
        )

    def _page(self, tool_name: str, arguments: dict[str, Any]) -> ResourcePage:
        payload = self._call(tool_name, arguments)
        return ResourcePage(
            items=tuple(
                self._resource_snapshot(item)
                for item in cast(list[dict[str, object]], payload["items"])
            ),
            next_page_token=_optional_string(payload.get("next_page_token")),
        )

    def _snapshot(self, tool_name: str, arguments: dict[str, Any]) -> ResourceSnapshot:
        payload = self._call(tool_name, arguments)
        return self._resource_snapshot(cast(dict[str, object], payload["item"]))

    def _call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, object]:
        try:
            payload = self._transport.call_tool(tool_name=tool_name, arguments=arguments).payload
        except MCPTransportError as error:
            raise _google_error_from_transport(error) from error
        return cast(dict[str, object], payload)

    def _resource_snapshot(self, item: dict[str, object]) -> ResourceSnapshot:
        return ResourceSnapshot(
            fixture_snapshot_id=str(item["fixture_snapshot_id"]),
            resource_type=ResourceType(str(item["resource_type"])),
            resource_id=str(item["resource_id"]),
            parent_id=_optional_string(item.get("parent_id")),
            related_resource_ids=tuple(
                str(value) for value in cast(list[object], item["related_resource_ids"])
            ),
            version=str(item["version"]),
            recovery_fingerprint=_optional_string(item.get("recovery_fingerprint")),
            payload=cast(dict[str, object], item["payload"]),
        )


def _google_error_from_transport(error: MCPTransportError) -> GoogleWorkspaceGatewayError:
    tool_error_map = {
        "INVALID_ARGUMENT": GoogleWorkspaceErrorCode.INVALID_ARGUMENT,
        "REAUTH_REQUIRED": GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        "OAUTH_NOT_CONNECTED": GoogleWorkspaceErrorCode.AUTH_EXPIRED,
        "PERMISSION_DENIED": GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        "NOT_FOUND": GoogleWorkspaceErrorCode.NOT_FOUND,
        "RATE_LIMITED": GoogleWorkspaceErrorCode.RATE_LIMITED,
        "UPSTREAM_5XX": GoogleWorkspaceErrorCode.UPSTREAM_5XX,
        "TIMEOUT": GoogleWorkspaceErrorCode.TIMEOUT,
        "INVALID_MCP_OUTPUT": GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        "MCP_UNAVAILABLE": GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
    }
    code_map = {
        MCPTransportErrorCode.TIMEOUT: GoogleWorkspaceErrorCode.TIMEOUT,
        MCPTransportErrorCode.CONNECTION_CLOSED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.PROCESS_UNAVAILABLE: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.NOT_FOUND: GoogleWorkspaceErrorCode.NOT_FOUND,
        MCPTransportErrorCode.SCHEMA_MISMATCH: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPTransportErrorCode.MALFORMED_RESPONSE: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPTransportErrorCode.TOOL_REJECTED: GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        MCPTransportErrorCode.HANDSHAKE_FAILED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.ARTIFACT_REJECTED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
    }
    return GoogleWorkspaceGatewayError(
        code=tool_error_map.get(str(error), code_map[error.code]),
        message=dumps({"safe_error": error.code.value, "detail": str(error)}, sort_keys=True),
        delivered=error.dispatch_started,
        mutated=False,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
