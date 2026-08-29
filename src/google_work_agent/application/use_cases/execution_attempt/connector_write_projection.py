"""Execution-attempt projection over the canonical ConnectorWritePort."""

from __future__ import annotations

from typing import cast

from google_work_agent.application.orchestration.connector_read_projection import (
    ConnectorReadProjection,
)
from google_work_agent.application.use_cases.execution_attempt.dispatch_connector_write import (
    DispatchConnectorWriteCommandV1,
    DispatchConnectorWriteHandler,
)
from google_work_agent.application.use_cases.execution_attempt.write_dispatch_models import (
    AuthorizedWriteDispatch,
    PreparedWriteDispatch,
    WriteResultMaterializer,
)
from google_work_agent.ports.connector.connector_write_port import ConnectorWriteResultV1
from google_work_agent.ports.connector.contracts.google_workspace import (
    DeliveryCertainty,
    GoogleWorkspaceErrorCode,
    GoogleWorkspaceGatewayError,
    ResourceSnapshot,
    ResourceType,
)


class ConnectorWriteProjection(WriteResultMaterializer):
    """Preserve broad write callers while all external I/O crosses the exact Port."""

    def __init__(
        self,
        *,
        dispatch_connector_write: DispatchConnectorWriteHandler,
        connector_reader: ConnectorReadProjection,
    ) -> None:
        self._dispatch_connector_write = dispatch_connector_write
        self._reader = connector_reader
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
        result = self.dispatch_write(request)
        if not result.success:
            certainty = DeliveryCertainty(result.delivery_certainty or "MAY_HAVE_BEEN_SENT")
            raise GoogleWorkspaceGatewayError(
                code=_error_code(result.error_code),
                message=result.error_code or "CONNECTOR_WRITE_FAILED",
                delivered=certainty is not DeliveryCertainty.NOT_SENT,
                mutated=certainty is DeliveryCertainty.SENT_RESPONSE_LOST,
                mcp_request_id=result.provider_request_id,
            )
        return self.materialize_success(request, result)

    def dispatch_write(self, request: AuthorizedWriteDispatch) -> ConnectorWriteResultV1:
        claim = request.claim_context
        result = self._dispatch_connector_write(
            DispatchConnectorWriteCommandV1(
                action_id=claim.action_id,
                approval_id=claim.approval_id,
                execution_attempt_id=claim.execution_attempt_id,
                tool_id=request.prepared.tool_name,
                tool_arguments=request.prepared.arguments,
                claim_context=claim,
            )
        ).connector_result
        self._last_request_id = result.provider_request_id
        return result

    def materialize_success(
        self,
        request: AuthorizedWriteDispatch,
        result: ConnectorWriteResultV1,
    ) -> ResourceSnapshot:
        if not result.success:
            raise ValueError("only a successful dispatch can be materialized")
        metadata = result.response_metadata or {}
        resource_id = _resource_id(request.prepared.arguments, metadata)
        payload = request.prepared.arguments.get("payload")
        return ResourceSnapshot(
            fixture_snapshot_id=str(metadata.get("fixture_snapshot_id") or resource_id),
            resource_type=ResourceType(
                str(metadata.get("resource_type") or _resource_type(request.prepared.tool_name))
            ),
            resource_id=resource_id,
            parent_id=cast(
                str | None,
                metadata.get("parent_id") or _parent_id(request.prepared.arguments),
            ),
            related_resource_ids=(),
            version=str(metadata.get("version") or "provider-write-result"),
            recovery_fingerprint=cast(
                str | None,
                metadata.get("recovery_fingerprint")
                or request.prepared.arguments.get("recovery_fingerprint"),
            ),
            payload=dict(payload) if isinstance(payload, dict) else {},
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
            return cast(tuple[ResourceSnapshot, ...], page.items)
        return ()

    def materialize_recovery_candidate(
        self,
        *,
        tool_name: str,
        arguments: dict[str, object],
        resource_id: str,
    ) -> ResourceSnapshot:
        """Read an already-existing result; this path never dispatches a Write."""
        return self._materialize_success(
            tool_name=tool_name,
            arguments=arguments,
            metadata={"resource_id": resource_id},
        )

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


def _parent_id(arguments: dict[str, object]) -> str | None:
    for key in ("task_list_id", "calendar_id"):
        value = arguments.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _error_code(value: str | None) -> GoogleWorkspaceErrorCode:
    mapping = {
        "TIMEOUT": GoogleWorkspaceErrorCode.TIMEOUT,
        "NOT_FOUND": GoogleWorkspaceErrorCode.NOT_FOUND,
        "PERMISSION_DENIED": GoogleWorkspaceErrorCode.PERMISSION_DENIED,
    }
    return mapping.get(value or "", GoogleWorkspaceErrorCode.CONNECTION_CLOSED)


__all__ = ["ConnectorWriteProjection"]
