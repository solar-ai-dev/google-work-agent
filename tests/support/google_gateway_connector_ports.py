"""Test-only bridge from the historical FakeGoogleGateway to canonical connector ports."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any, cast

from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    AuthorizedWriteDispatch,
    PreparedWriteDispatch,
)
from google_work_agent.ports.connector.connector_failure import (
    ConnectorFailureCode,
    ConnectorOperationFailure,
)
from google_work_agent.ports.connector.connector_read_port import (
    ConnectorReadResultV1,
    JsonValue,
)
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.connector.contracts import ValidatedConnectorToolBindingV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourcePage,
    ResourceSnapshot,
    ResourceType,
    TimeRange,
)


@dataclass(frozen=True, slots=True)
class GoogleGatewayConnectorReadPort:
    gateway: Any

    def execute_read(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
    ) -> ConnectorReadResultV1:
        arguments = cast(dict[str, object], tool_arguments)
        tool_id = binding.tool_id
        if tool_id == "gmail_search_threads":
            query = str(arguments.get("query", ""))
            if len(query) == 64:
                value = ResourcePage(
                    self.gateway.search_by_recovery_fingerprint(
                        resource_type=ResourceType.GMAIL_MESSAGE,
                        recovery_fingerprint=query,
                    ),
                    None,
                )
            else:
                value = self.gateway.search_gmail_threads(
                    query=query,
                    page_token=cast(str | None, arguments.get("page_token")),
                    page_size=int(arguments.get("page_size", 50)),
                )
            output = _page(value)
        elif tool_id == "gmail_get_thread":
            output = _item(
                _read_one(
                    lambda: self.gateway.get_gmail_thread(thread_id=str(arguments["thread_id"]))
                )
            )
        elif tool_id == "gmail_get_message":
            output = _item(
                _read_one(
                    lambda: self.gateway.get_gmail_message(message_id=str(arguments["message_id"]))
                )
            )
        elif tool_id == "gmail_get_draft":
            output = _item(
                _read_one(lambda: self.gateway.get_gmail_draft(draft_id=str(arguments["draft_id"])))
            )
        elif tool_id == "tasks_list_tasklists":
            output = _page(
                self.gateway.list_task_lists(
                    page_token=cast(str | None, arguments.get("page_token")),
                    page_size=int(arguments.get("page_size", 50)),
                )
            )
        elif tool_id == "tasks_list_tasks":
            query = arguments.get("query")
            output = (
                _page(
                    ResourcePage(
                        self.gateway.search_by_recovery_fingerprint(
                            resource_type=ResourceType.TASK,
                            recovery_fingerprint=str(query),
                        ),
                        None,
                    )
                )
                if isinstance(query, str) and query
                else _page(
                    self.gateway.list_tasks(
                        task_list_id=str(arguments["task_list_id"]),
                        page_token=cast(str | None, arguments.get("page_token")),
                        page_size=int(arguments.get("page_size", 50)),
                    )
                )
            )
        elif tool_id == "tasks_get_task":
            output = _item(
                _read_one(
                    lambda: self.gateway.get_task(
                        task_list_id=str(arguments["task_list_id"]),
                        task_id=str(arguments["task_id"]),
                    )
                )
            )
        elif tool_id == "calendar_list_calendars":
            output = _page(
                self.gateway.list_calendars(
                    page_token=cast(str | None, arguments.get("page_token")),
                    page_size=int(arguments.get("page_size", 50)),
                )
            )
        elif tool_id == "calendar_list_events":
            output = _page(
                self.gateway.list_calendar_events(
                    calendar_id=str(arguments["calendar_id"]),
                    page_token=cast(str | None, arguments.get("page_token")),
                    page_size=int(arguments.get("page_size", 50)),
                    time_min=cast(str | None, arguments.get("time_min")),
                    time_max=cast(str | None, arguments.get("time_max")),
                    single_events=bool(arguments.get("single_events", False)),
                    order_by=cast(str | None, arguments.get("order_by")),
                )
            )
        elif tool_id == "calendar_query_freebusy":
            calendars = self.gateway.query_freebusy(
                calendar_ids=tuple(cast(list[str], arguments["calendar_ids"])),
                time_range=TimeRange(str(arguments["time_min"]), str(arguments["time_max"])),
            )
            output = {
                "calendars": [
                    {
                        "calendar_id": calendar.calendar_id,
                        "intervals": [asdict(interval) for interval in calendar.intervals],
                    }
                    for calendar in calendars
                ]
            }
        elif tool_id == "calendar_get_event":
            output = _item(
                _read_one(
                    lambda: self.gateway.get_calendar_event(
                        calendar_id=str(arguments["calendar_id"]),
                        event_id=str(arguments["event_id"]),
                    )
                )
            )
        else:
            raise LookupError(f"unsupported test read tool: {tool_id}")
        return ConnectorReadResultV1(
            schema_version=1,
            tool_id=tool_id,
            request_id=str(getattr(self.gateway, "last_request_id", "test-request") or ""),
            output=cast(dict[str, JsonValue], output),
            next_page_token=cast(str | None, output.get("next_page_token")),
            total_count=None,
        )


@dataclass(frozen=True, slots=True)
class GoogleGatewayConnectorWritePort:
    gateway: Any

    def execute_write(
        self,
        binding: ValidatedConnectorToolBindingV1,
        tool_arguments: dict[str, JsonValue],
        claim_token: dict[str, JsonValue],
    ) -> ConnectorWriteResultV1:
        arguments = cast(dict[str, object], tool_arguments)
        prepare = getattr(self.gateway, "prepare_claim_context", None)
        claim_context = (
            cast(
                dict[str, object],
                prepare(
                    claim_payload=cast(dict[str, object], claim_token),
                    tool_name=binding.tool_id,
                    approval_arguments_hash=str(claim_token["approval_arguments_hash"]),
                    execution_arguments_hash=str(claim_token["execution_arguments_hash"]),
                ),
            )
            if callable(prepare)
            else cast(dict[str, object], claim_token)
        )
        try:
            snapshot = self._dispatch(binding.tool_id, arguments, claim_context)
        except GoogleWorkspaceGatewayError as error:
            error_code = (
                "AUTH_REQUIRED"
                if error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
                else error.code.value
            )
            return ConnectorWriteResultV1(
                1,
                False,
                error.delivery_certainty.value,
                error.mcp_request_id,
                None,
                error_code,
            )
        metadata: dict[str, str | int | float | bool | None] = {
            "resource_id": snapshot.resource_id,
            "resource_type": snapshot.resource_type.value,
            "fixture_snapshot_id": snapshot.fixture_snapshot_id,
            "parent_id": snapshot.parent_id,
            "version": snapshot.version,
            "recovery_fingerprint": snapshot.recovery_fingerprint,
        }
        return ConnectorWriteResultV1(
            1,
            True,
            None,
            str(getattr(self.gateway, "last_request_id", "test-request") or ""),
            metadata,
            None,
        )

    def _dispatch(
        self, tool_id: str, arguments: dict[str, object], claim_context: dict[str, object]
    ) -> ResourceSnapshot:
        if tool_id == "gmail_send":
            return self.gateway.send_gmail(
                draft_id=str(arguments["draft_id"]),
                recovery_fingerprint=cast(str | None, arguments.get("recovery_fingerprint")),
                claim_context=claim_context,
            )
        if tool_id == "calendar_delete_event":
            return self.gateway.delete_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                event_id=str(arguments["event_id"]),
                claim_context=claim_context,
            )
        if tool_id == "tasks_delete_task":
            return self.gateway.delete_task(
                task_list_id=str(arguments["task_list_id"]),
                task_id=str(arguments["task_id"]),
                claim_context=claim_context,
            )
        payload = cast(dict[str, object], arguments["payload"])
        if tool_id == "gmail_create_draft":
            return self.gateway.create_gmail_draft(payload=payload, claim_context=claim_context)
        if tool_id == "gmail_update_draft":
            return self.gateway.update_gmail_draft(
                draft_id=str(arguments["draft_id"]),
                payload=payload,
                claim_context=claim_context,
            )
        if tool_id == "tasks_create_task":
            return self.gateway.create_task(
                task_list_id=str(arguments["task_list_id"]),
                payload=payload,
                claim_context=claim_context,
            )
        if tool_id == "tasks_update_task":
            return self.gateway.update_task(
                task_list_id=str(arguments["task_list_id"]),
                task_id=str(arguments["task_id"]),
                payload=payload,
                claim_context=claim_context,
            )
        if tool_id == "calendar_create_event":
            return self.gateway.create_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                payload=payload,
                claim_context=claim_context,
            )
        if tool_id == "calendar_update_event":
            return self.gateway.update_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                event_id=str(arguments["event_id"]),
                payload=payload,
                claim_context=claim_context,
            )
        raise LookupError(f"unsupported test write tool: {tool_id}")


class LegacyGatewayWriteProjection:
    """Test compatibility for fixtures that construct a workflow in one expression."""

    def __init__(self, *, gateway: Any) -> None:
        self._gateway = gateway
        self._port = GoogleGatewayConnectorWritePort(gateway)
        self._last_snapshot: ResourceSnapshot | None = None
        self._last_request_id: str | None = None

    @property
    def last_request_id(self) -> str | None:
        return self._last_request_id

    def prepare_write(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        recovery_fingerprint: str | None,
    ) -> PreparedWriteDispatch:
        return PreparedWriteDispatch(
            tool_name,
            _final_arguments(tool_name, arguments, recovery_fingerprint),
        )

    def dispatch_write(self, request: AuthorizedWriteDispatch) -> ConnectorWriteResultV1:
        try:
            snapshot = self._port._dispatch(
                request.prepared.tool_name,
                request.prepared.arguments,
                request.claim_payload,
            )
        except GoogleWorkspaceGatewayError as error:
            code = (
                "AUTH_REQUIRED"
                if error.code is GoogleWorkspaceErrorCode.AUTH_EXPIRED
                else error.code.value
            )
            return ConnectorWriteResultV1(
                1,
                False,
                error.delivery_certainty.value,
                error.mcp_request_id,
                None,
                code,
            )
        self._last_snapshot = snapshot
        self._last_request_id = str(getattr(self._gateway, "last_request_id", "test-request") or "")
        return ConnectorWriteResultV1(
            1,
            True,
            None,
            self._last_request_id,
            {"resource_id": snapshot.resource_id},
            None,
        )

    def materialize_success(
        self, _request: AuthorizedWriteDispatch, _result: ConnectorWriteResultV1
    ) -> ResourceSnapshot:
        if self._last_snapshot is None:
            raise RuntimeError("test write result was not captured")
        return self._last_snapshot

    def materialize_recovery_candidate(
        self, *, tool_name: str, arguments: dict[str, object], resource_id: str
    ) -> ResourceSnapshot:
        return self.fetch_verification_snapshot(
            tool_name=tool_name,
            arguments=arguments,
            fallback_resource_id=resource_id,
        )

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot:
        resource_id = str(
            arguments.get("draft_id")
            or arguments.get("task_id")
            or arguments.get("event_id")
            or fallback_resource_id
        )
        if tool_name.startswith("gmail_"):
            return (
                self._gateway.get_gmail_message(message_id=resource_id)
                if tool_name == "gmail_send"
                else self._gateway.get_gmail_draft(draft_id=resource_id)
            )
        if tool_name.startswith("tasks_"):
            return self._gateway.get_task(
                task_list_id=str(arguments["task_list_id"]), task_id=resource_id
            )
        return self._gateway.get_calendar_event(
            calendar_id=str(arguments["calendar_id"]), event_id=resource_id
        )

    def search_recovery_candidates(
        self, *, tool_name: str, recovery_fingerprint: str
    ) -> tuple[ResourceSnapshot, ...]:
        resource_type = (
            ResourceType.GMAIL_MESSAGE
            if tool_name == "gmail_send"
            else ResourceType.GMAIL_DRAFT
            if tool_name.startswith("gmail_")
            else ResourceType.TASK
            if tool_name.startswith("tasks_")
            else ResourceType.CALENDAR_EVENT
        )
        return self._gateway.search_by_recovery_fingerprint(
            resource_type=resource_type,
            recovery_fingerprint=recovery_fingerprint,
        )


def _item(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {"item": _snapshot(snapshot)}


def _read_one(read: Callable[[], ResourceSnapshot]) -> ResourceSnapshot:
    try:
        return read()
    except LookupError as error:
        raise ConnectorOperationFailure(
            ConnectorFailureCode.NOT_FOUND,
            "TEST_RESOURCE_NOT_FOUND",
        ) from error


def _page(page: ResourcePage) -> dict[str, object]:
    return {
        "items": [_snapshot(item) for item in page.items],
        "next_page_token": page.next_page_token,
    }


def _snapshot(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {
        "fixture_snapshot_id": snapshot.fixture_snapshot_id,
        "resource_type": ResourceType(snapshot.resource_type).value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "related_resource_ids": list(snapshot.related_resource_ids),
        "version": snapshot.version,
        "recovery_fingerprint": snapshot.recovery_fingerprint,
        "payload": snapshot.payload,
    }


def _final_arguments(
    tool_name: str,
    arguments: dict[str, object],
    recovery_fingerprint: str | None,
) -> dict[str, object]:
    if tool_name == "gmail_send":
        return {
            "draft_id": str(arguments["draft_id"]),
            "recovery_fingerprint": recovery_fingerprint,
        }
    if tool_name == "calendar_delete_event":
        return {
            "calendar_id": str(arguments["calendar_id"]),
            "event_id": str(arguments["event_id"]),
        }
    if tool_name == "tasks_delete_task":
        return {
            "task_list_id": str(arguments["task_list_id"]),
            "task_id": str(arguments["task_id"]),
        }
    payload = cast(dict[str, object], arguments["payload"])
    normalized = dict(payload)
    if recovery_fingerprint is not None and tool_name in {
        "gmail_create_draft",
        "tasks_create_task",
        "calendar_create_event",
    }:
        normalized["recovery_fingerprint"] = recovery_fingerprint
    identity = {
        key: value
        for key, value in arguments.items()
        if key in {"draft_id", "task_list_id", "task_id", "calendar_id", "event_id"}
    }
    return {**identity, "payload": normalized}


__all__ = [
    "GoogleGatewayConnectorReadPort",
    "GoogleGatewayConnectorWritePort",
    "LegacyGatewayWriteProjection",
]
