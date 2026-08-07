"""Google Workspace gateway implemented over MCP tools."""

from __future__ import annotations

from json import dumps
from typing import Any, cast

from google_work_agent.ports import (
    FreeBusyCalendar,
    FreeBusyInterval,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGateway,
    GoogleWorkspaceGatewayError,
    MCPTransport,
    MCPTransportError,
    MCPTransportErrorCode,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
)


class MCPGoogleWorkspaceGateway(GoogleWorkspaceGateway):
    def __init__(self, *, transport: MCPTransport) -> None:
        self._transport = transport

    def prepare_claim_context(
        self,
        *,
        claim_payload: dict[str, object],
        tool_name: str,
        canonical_arguments_hash: str,
    ) -> dict[str, object]:
        transport = cast(Any, self._transport)
        process_instance_id = cast(str | None, getattr(transport, "process_instance_id", None))
        if process_instance_id is None:
            raise RuntimeError("mcp process instance id is unavailable")
        payload = {
            "action_id": str(claim_payload["action_id"]),
            "approval_id": str(claim_payload["approval_id"]),
            "execution_attempt_id": str(claim_payload["attempt_id"]),
            "tool_name": tool_name,
            "canonical_arguments_hash": canonical_arguments_hash,
            "service_instance_id": str(claim_payload["service_instance_id"]),
            "mcp_process_instance_id": process_instance_id,
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
    ) -> ResourcePage:
        return self._page(
            "calendar_list_events",
            {"calendar_id": calendar_id, "page_token": page_token, "page_size": page_size},
        )

    def query_freebusy(self, *, calendar_ids: tuple[str, ...]) -> tuple[FreeBusyCalendar, ...]:
        payload = self._call("calendar_query_freebusy", {"calendar_ids": list(calendar_ids)})
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
    code_map = {
        MCPTransportErrorCode.TIMEOUT: GoogleWorkspaceErrorCode.TIMEOUT,
        MCPTransportErrorCode.CONNECTION_CLOSED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.PROCESS_UNAVAILABLE: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.SCHEMA_MISMATCH: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPTransportErrorCode.MALFORMED_RESPONSE: GoogleWorkspaceErrorCode.RESPONSE_MALFORMED,
        MCPTransportErrorCode.TOOL_REJECTED: GoogleWorkspaceErrorCode.PERMISSION_DENIED,
        MCPTransportErrorCode.HANDSHAKE_FAILED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
        MCPTransportErrorCode.ARTIFACT_REJECTED: GoogleWorkspaceErrorCode.CONNECTION_CLOSED,
    }
    return GoogleWorkspaceGatewayError(
        code=code_map[error.code],
        message=dumps({"safe_error": error.code.value, "detail": str(error)}, sort_keys=True),
        delivered=error.code is not MCPTransportErrorCode.TIMEOUT,
        mutated=False,
    )


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)
