"""Bounded caller projection over the canonical ConnectorWritePort."""

from __future__ import annotations

from typing import cast

from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteCommand,
    DispatchConnectorWriteHandler,
)
from google_work_agent.application.write_dispatch_models import (
    AuthorizedWriteDispatch,
    PreparedWriteDispatch,
    WriteResultMaterializer,
)
from google_work_agent.ports import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
)
from google_work_agent.ports.connector.connector_read_port import JsonValue


class ConnectorWriteProjection(WriteResultMaterializer):
    """Preserve broad write callers while all external I/O crosses the exact Port."""

    def __init__(
        self,
        *,
        dispatch_connector_write: DispatchConnectorWriteHandler,
        connector_reader: ConnectorReadProjection,
        connector_id: str = "google_workspace",
    ) -> None:
        self._dispatch_connector_write = dispatch_connector_write
        self._reader = connector_reader
        self._connector_id = connector_id
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
            tool_name=tool_name,
            arguments=_final_arguments(
                tool_name,
                arguments,
                recovery_fingerprint=recovery_fingerprint,
            ),
        )

    def execute_write(self, request: AuthorizedWriteDispatch) -> ResourceSnapshot:
        claim = _claim_context(request)
        result = self._dispatch_connector_write(
            DispatchConnectorWriteCommand(
                schema_version=1,
                connector_id=self._connector_id,
                tool_id=request.prepared.tool_name,
                tool_arguments=cast(dict[str, JsonValue], request.prepared.arguments),
                claim_token=cast(dict[str, JsonValue], claim),
                approval_arguments_hash=request.approval_arguments_hash,
                execution_arguments_hash=request.execution_arguments_hash,
            )
        ).connector_result
        self._last_request_id = result.provider_request_id
        if not result.success:
            certainty = DeliveryCertainty(result.delivery_certainty or "MAY_HAVE_BEEN_SENT")
            raise GoogleWorkspaceGatewayError(
                code=_error_code(result.error_code),
                message=result.error_code or "CONNECTOR_WRITE_FAILED",
                delivered=certainty is not DeliveryCertainty.NOT_SENT,
                mutated=certainty is DeliveryCertainty.SENT_RESPONSE_LOST,
                mcp_request_id=result.provider_request_id,
            )
        return self._materialize_success(
            tool_name=request.prepared.tool_name,
            arguments=request.prepared.arguments,
            metadata=result.response_metadata or {},
        )

    def fetch_verification_snapshot(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        fallback_resource_id: str | None,
    ) -> ResourceSnapshot:
        return self._materialize_success(
            tool_name=tool_name,
            arguments=arguments,
            metadata={} if fallback_resource_id is None else {"resource_id": fallback_resource_id},
        )

    def search_recovery_candidates(
        self,
        *,
        tool_name: str,
        recovery_fingerprint: str,
    ) -> tuple[ResourceSnapshot, ...]:
        if tool_name.startswith("gmail_"):
            page = self._reader.search_gmail_threads(
                query=recovery_fingerprint,
                page_token=None,
                page_size=50,
            )
            return page.items
        return ()

    def _materialize_success(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        metadata: dict[str, str | int | float | bool | None],
    ) -> ResourceSnapshot:
        resource_id = _resource_id(arguments, metadata)
        if tool_name in {"gmail_create_draft", "gmail_update_draft"}:
            return self._reader.get_gmail_draft(draft_id=resource_id)
        if tool_name == "gmail_send":
            return self._reader.get_gmail_message(message_id=resource_id)
        if tool_name.startswith("tasks_") and "delete" not in tool_name:
            return self._reader.get_task(
                task_list_id=str(arguments["task_list_id"]),
                task_id=resource_id,
            )
        if tool_name.startswith("calendar_") and "delete" not in tool_name:
            return self._reader.get_calendar_event(
                calendar_id=str(arguments["calendar_id"]),
                event_id=resource_id,
            )
        return ResourceSnapshot(
            fixture_snapshot_id=str(metadata.get("fixture_snapshot_id") or resource_id),
            resource_type=ResourceType(
                str(metadata.get("resource_type") or _resource_type(tool_name))
            ),
            resource_id=resource_id,
            parent_id=cast(str | None, metadata.get("parent_id")),
            related_resource_ids=(),
            version=str(metadata.get("version") or "deleted"),
            recovery_fingerprint=cast(str | None, metadata.get("recovery_fingerprint")),
            payload={"deleted": True},
        )


def _claim_context(request: AuthorizedWriteDispatch) -> dict[str, object]:
    payload = request.claim_payload
    return {
        "claim_version": 2,
        "action_id": str(payload["action_id"]),
        "approval_id": str(payload["approval_id"]),
        "execution_attempt_id": str(payload["attempt_id"]),
        "tool_name": request.prepared.tool_name,
        "approval_arguments_hash": request.approval_arguments_hash,
        "execution_arguments_hash": request.execution_arguments_hash,
        "service_instance_id": str(payload["service_instance_id"]),
        "issued_at_ms": int(str(payload["issued_at_ms"])),
        "expires_at_ms": int(str(payload["expires_at_ms"])),
        "nonce": str(payload["nonce"]),
    }


def _final_arguments(
    tool_name: str,
    arguments: dict[str, object],
    *,
    recovery_fingerprint: str | None,
) -> dict[str, object]:
    if tool_name == "gmail_send":
        return {
            "draft_id": _required(arguments, "draft_id"),
            "recovery_fingerprint": recovery_fingerprint,
        }
    if tool_name == "calendar_delete_event":
        return {
            "calendar_id": _required(arguments, "calendar_id"),
            "event_id": _required(arguments, "event_id"),
        }
    if tool_name == "tasks_delete_task":
        return {
            "task_list_id": _required(arguments, "task_list_id"),
            "task_id": _required(arguments, "task_id"),
        }
    payload = arguments.get("payload")
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    normalized_payload = dict(payload)
    if recovery_fingerprint is not None and tool_name in {
        "gmail_create_draft",
        "tasks_create_task",
        "calendar_create_event",
    }:
        normalized_payload["recovery_fingerprint"] = recovery_fingerprint
    identity = {
        key: value
        for key, value in arguments.items()
        if key in {"draft_id", "task_list_id", "task_id", "calendar_id", "event_id"}
    }
    return {**identity, "payload": normalized_payload}


def _required(arguments: dict[str, object], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _resource_id(
    arguments: dict[str, object],
    metadata: dict[str, str | int | float | bool | None],
) -> str:
    value = metadata.get("resource_id")
    if isinstance(value, str) and value:
        return value
    for key in ("draft_id", "task_id", "event_id"):
        argument_value = arguments.get(key)
        if isinstance(argument_value, str) and argument_value:
            return argument_value
    raise LookupError("connector write response omitted resource identity")


def _resource_type(tool_name: str) -> str:
    if tool_name.startswith("tasks_"):
        return "task"
    if tool_name.startswith("calendar_"):
        return "calendar_event"
    return "gmail_message"


def _error_code(value: str | None) -> GoogleWorkspaceErrorCode:
    mapping = {
        "TIMEOUT": GoogleWorkspaceErrorCode.TIMEOUT,
        "NOT_FOUND": GoogleWorkspaceErrorCode.NOT_FOUND,
        "PERMISSION_DENIED": GoogleWorkspaceErrorCode.PERMISSION_DENIED,
    }
    return mapping.get(value or "", GoogleWorkspaceErrorCode.CONNECTION_CLOSED)


__all__ = ["ConnectorWriteProjection"]
