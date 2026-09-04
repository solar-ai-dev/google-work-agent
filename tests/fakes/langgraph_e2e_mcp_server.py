"""Deterministic external Google Workspace MCP fake for real-composition E2E tests."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from google_work_agent.adapters.connectors.google.workspace.mcp_server import project_registry
from google_work_agent.adapters.connectors.google.workspace.mcp_server import (
    validate_claim_context as claim_context_validation,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.credential_provider import (
    _WorkspaceToolError,
)
from google_work_agent.adapters.connectors.google.workspace.mcp_server.project_registry import (
    google_workspace_tool_contract,
    validate_tool_input,
    validate_tool_output,
)
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)

_PROCESS_INSTANCE_ID = "e2e-mcp-process"
_claim_state = SimpleNamespace(
    session_key=None,
    service_instance_id=None,
    process_instance_id=_PROCESS_INSTANCE_ID,
    used_nonces=set(),
)


def main() -> None:
    _append_runtime_event({"event_type": "PROCESS_STARTED", "pid": os.getpid()})
    for line in sys.stdin:
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        message_type = request.get("type")
        if message_type == "shutdown":
            return
        try:
            payload = _dispatch(request)
        except _ExternalFailure as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": error.code,
                        "message": error.code,
                        "delivery_certainty": error.delivery_certainty,
                    },
                }
            )
            continue
        except _WorkspaceToolError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": str(error),
                        "delivery_certainty": "NOT_SENT",
                    },
                }
            )
            continue
        _write({"id": request_id, "payload": payload})


def _dispatch(request: dict[str, object]) -> dict[str, object]:
    message_type = str(request.get("type", ""))
    if message_type == "handshake":
        _claim_state.session_key = str(request["session_key"])
        _claim_state.service_instance_id = str(request["service_instance_id"])
        return {"process_instance_id": _PROCESS_INSTANCE_ID}
    if message_type == "initialize":
        return {
            "protocol_version": "2026-08-07.p0",
            "manifest_version": request["manifest_version"],
            "registry_manifest_hash": request["registry_manifest_hash"],
        }
    if message_type == "list_tools":
        return {
            "tool_names": sorted(entry.tool_name for entry in load_signed_tool_registry().entries)
        }
    if message_type == "control_call":
        return _control_payload(str(request.get("method", "")))
    if message_type != "tool_call":
        return {}
    tool_name = str(request["tool_name"])
    arguments = cast(dict[str, object], request.get("arguments") or {})
    validate_tool_input(tool_name, arguments)
    if tool_name in _write_tools():
        claim_context_validation.validate_claim_context(
            _claim_state,
            tool_name=tool_name,
            claim_context=arguments.get("claim_context"),
            execution_arguments={
                key: value for key, value in arguments.items() if key != "claim_context"
            },
        )
    _append_event({"tool_name": tool_name, "arguments": arguments})
    payload = _tool_payload(tool_name, arguments)
    validate_tool_output(tool_name, payload)
    return payload


def _control_payload(method: str) -> dict[str, object]:
    if method in {"mcp.list_project_registry", "mcp.list_internal_capabilities"}:
        return {
            "internal_capability_registry_version": (
                project_registry.INTERNAL_CAPABILITY_REGISTRY_VERSION
            ),
            "internal_capability_names": sorted(
                capability.tool_name
                for capability in project_registry.build_google_workspace_internal_capabilities()
            ),
        }
    if method == "mcp.list_capability_contracts":
        internal_categories = {
            capability.tool_name: capability.category.value
            for capability in project_registry.build_google_workspace_internal_capabilities()
        }
        names = {entry.tool_name for entry in load_signed_tool_registry().entries} | set(
            internal_categories
        )
        return {
            "contracts": [
                {
                    "tool_name": name,
                    "category": internal_categories.get(name, "AGENT_TOOL"),
                    "input_schema_version": google_workspace_tool_contract(
                        name
                    ).input_schema_version,
                    "output_schema_version": google_workspace_tool_contract(
                        name
                    ).output_schema_version,
                    "tool_schema_hash": google_workspace_tool_contract(name).schema_hash,
                }
                for name in sorted(names)
            ]
        }
    if method == "google.connection.get":
        state = _load_state()
        reauth_required = bool(state.get("reauth_required"))
        return {
            "connected": not reauth_required,
            "credential_state": "REAUTH_REQUIRED" if reauth_required else "CONNECTED",
            "account_id": "e2e-google-account",
            "account_email": "e2e@example.com",
            "display_name": "E2E User",
            "granted_scopes": [
                "openid",
                "userinfo.email",
                "gmail.readonly",
                "gmail.compose",
                "tasks",
                "calendar.events",
                "calendarlist.readonly",
                "calendar.events.freebusy",
            ],
            "missing_scopes": [],
            "reauth_required": reauth_required,
            "oauth_environment": "DEVELOPMENT",
            "last_checked_at_ms": 1,
        }
    if method == "google.connection.refresh":
        return {"access_context_handle": "e2e-access-context"}
    return {
        "status": "SAFE_TO_RETRY",
        "result_ref": None,
        "bounded_result": None,
    }


def _tool_payload(tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    state = _load_state()
    counts = cast(dict[str, int], state.setdefault("counts", {}))
    counts[tool_name] = int(counts.get(tool_name, 0)) + 1
    failure_mode = _failure_mode(arguments)
    fault_counts = cast(dict[str, int], state.setdefault("fault_counts", {}))
    claim_context = arguments.get("claim_context")
    action_id = (
        claim_context.get("action_id") if isinstance(claim_context, dict) else None
    )
    fault_key = f"{failure_mode}:{tool_name}:{action_id}"
    fault_counts[fault_key] = int(fault_counts.get(fault_key, 0)) + 1
    fault_count = fault_counts[fault_key]
    if failure_mode == "FAILED_RETRY" and fault_count == 1:
        _save_state(state)
        raise _ExternalFailure("TOOL_REJECTED", "NOT_SENT")
    if failure_mode == "REAUTH" and fault_count == 1:
        state["reauth_required"] = True
        _save_state(state)
        raise _ExternalFailure("AUTH_REQUIRED", "NOT_SENT")
    if failure_mode == "MCP_FAILURE" and fault_count == 1:
        _save_state(state)
        os._exit(70)

    if tool_name == "search_by_recovery_fingerprint":
        fingerprint = str(arguments["recovery_fingerprint"])
        items = [
            item
            for item in cast(dict[str, dict[str, object]], state.get("resources", {})).values()
            if item.get("recovery_fingerprint") == fingerprint
        ]
        _save_state(state)
        return {"items": items}
    if tool_name == "calendar_query_freebusy":
        _save_state(state)
        return {
            "calendars": [
                {"calendar_id": item, "intervals": []}
                for item in cast(list[str], arguments["calendar_ids"])
            ]
        }
    if tool_name in {
        "gmail_search_threads",
        "tasks_list_tasklists",
        "tasks_list_tasks",
        "calendar_list_calendars",
        "calendar_list_events",
    }:
        query = arguments.get("query")
        if isinstance(query, str) and query:
            items = [
                item
                for item in cast(dict[str, dict[str, object]], state.get("resources", {})).values()
                if _resource_matches_list_tool(item, tool_name=tool_name)
                and query in json.dumps(item, sort_keys=True)
            ]
            if not items and tool_name == "gmail_search_threads":
                items = [_read_fixture(tool_name, arguments)]
            resources = cast(dict[str, dict[str, object]], state.setdefault("resources", {}))
            for item in items:
                resources[_resource_key(item)] = item
            _save_state(state)
            return {"items": items, "next_page_token": None}
        item = _read_fixture(tool_name, arguments)
        resources = cast(dict[str, dict[str, object]], state.setdefault("resources", {}))
        resources[_resource_key(item)] = item
        _save_state(state)
        return {"items": [item], "next_page_token": None}
    if tool_name in _write_tools():
        item = _write_fixture(tool_name, arguments, counts[tool_name])
        resources = cast(dict[str, dict[str, object]], state.setdefault("resources", {}))
        resources[_resource_key(item)] = item
        _save_state(state)
        if failure_mode in {
            "UNKNOWN_RESULT",
            "UNKNOWN_RESULT_RECOVERY",
            "RESPONSE_LOSS",
        }:
            raise _ExternalFailure("TIMEOUT", "SENT_RESPONSE_LOST")
        return {"item": item}
    if tool_name in {
        "gmail_get_message",
        "gmail_get_thread",
        "gmail_get_draft",
        "tasks_get_task",
        "calendar_get_event",
    }:
        read_item = _get_fixture(tool_name, arguments, state)
        if read_item is None:
            raise _ExternalFailure("NOT_FOUND", "NOT_SENT")
        item_failure_mode = _failure_mode(
            {"payload": cast(dict[str, object], read_item.get("payload") or {})}
        )
        if item_failure_mode == "VERIFICATION_MISMATCH" or (
            item_failure_mode == "RECOVERY" and counts[tool_name] == 1
        ):
            observed_payload = cast(dict[str, object], read_item["payload"])
            read_item = {
                **read_item,
                "payload": {**observed_payload, "title": "mismatch-observed"},
            }
        _save_state(state)
        return {"item": read_item}
    _save_state(state)
    return {"item": _read_fixture(tool_name, arguments)}


def _read_fixture(tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
    if tool_name.startswith("gmail"):
        return _snapshot(
            "gmail_thread",
            "gmail-thread-e2e",
            None,
            {"subject": "E2E mail", "snippet": "deterministic Gmail evidence"},
        )
    if tool_name == "tasks_list_tasklists":
        return _snapshot("task_list", "task-list-e2e", None, {"title": "E2E Tasks"})
    if tool_name.startswith("tasks"):
        return _snapshot(
            "task",
            "task-read-e2e",
            str(arguments.get("task_list_id", "task-list-e2e")),
            {"title": "E2E task", "status": "needsAction"},
        )
    if tool_name == "calendar_list_calendars":
        return _snapshot(
            "calendar",
            "calendar-e2e",
            None,
            {"summary": "E2E Calendar", "primary": True},
        )
    return _snapshot(
        "calendar_event",
        "event-read-e2e",
        str(arguments.get("calendar_id", "calendar-e2e")),
        {
            "title": "E2E event",
            "start": "2026-09-03T09:00:00+09:00",
            "end": "2026-09-03T10:00:00+09:00",
        },
    )


def _write_fixture(
    tool_name: str,
    arguments: dict[str, object],
    count: int,
) -> dict[str, object]:
    payload = dict(cast(dict[str, object], arguments.get("payload") or {}))
    fingerprint = arguments.get("recovery_fingerprint") or payload.get("recovery_fingerprint")
    if tool_name.startswith("tasks"):
        resource_type = "task"
        resource_id = str(arguments.get("task_id") or f"task-write-{count}")
        parent_id = str(arguments.get("task_list_id", "task-list-e2e"))
    elif tool_name.startswith("calendar"):
        resource_type = "calendar_event"
        resource_id = str(arguments.get("event_id") or f"event-write-{count}")
        parent_id = str(arguments.get("calendar_id", "calendar-e2e"))
    elif "draft" in tool_name:
        resource_type = "gmail_draft"
        resource_id = str(arguments.get("draft_id") or f"draft-write-{count}")
        parent_id = None
    else:
        resource_type = "gmail_message"
        resource_id = f"message-write-{count}"
        parent_id = None
    return _snapshot(
        resource_type,
        resource_id,
        parent_id,
        payload,
        recovery_fingerprint=None if fingerprint is None else str(fingerprint),
    )


def _get_fixture(
    tool_name: str,
    arguments: dict[str, object],
    state: dict[str, object],
) -> dict[str, object] | None:
    if tool_name.startswith("tasks"):
        key = f"task:{arguments.get('task_id')}"
    elif tool_name.startswith("calendar"):
        key = f"calendar_event:{arguments.get('event_id')}"
    elif "draft" in tool_name:
        key = f"gmail_draft:{arguments.get('draft_id')}"
    elif tool_name == "gmail_get_thread":
        key = f"gmail_thread:{arguments.get('thread_id')}"
    else:
        key = f"gmail_message:{arguments.get('message_id')}"
    return cast(dict[str, dict[str, object]], state.get("resources", {})).get(key)


def _snapshot(
    resource_type: str,
    resource_id: str,
    parent_id: str | None,
    payload: dict[str, object],
    *,
    recovery_fingerprint: str | None = None,
) -> dict[str, object]:
    return {
        "fixture_snapshot_id": f"snapshot:{resource_type}:{resource_id}",
        "resource_type": resource_type,
        "resource_id": resource_id,
        "parent_id": parent_id,
        "related_resource_ids": [] if parent_id is None else [parent_id],
        "version": "v1",
        "recovery_fingerprint": recovery_fingerprint,
        "payload": payload,
    }


def _resource_key(item: dict[str, object]) -> str:
    return f"{item['resource_type']}:{item['resource_id']}"


def _resource_matches_list_tool(item: Mapping[str, object], *, tool_name: str) -> bool:
    resource_type = item.get("resource_type")
    expected = {
        "gmail_search_threads": {"gmail_thread"},
        "tasks_list_tasklists": {"task_list"},
        "tasks_list_tasks": {"task"},
        "calendar_list_calendars": {"calendar"},
        "calendar_list_events": {"calendar_event"},
    }
    return resource_type in expected[tool_name]


def _failure_mode(arguments: dict[str, object]) -> str | None:
    payload = arguments.get("payload")
    title = payload.get("title") if isinstance(payload, dict) else None
    normalized = title.upper() if isinstance(title, str) else ""
    for value in (
        "UNKNOWN_RESULT_RECOVERY",
        "VERIFICATION_MISMATCH",
        "FAILED_RETRY",
        "UNKNOWN_RESULT",
        "RESPONSE_LOSS",
        "MCP_FAILURE",
        "RECOVERY",
        "REAUTH",
    ):
        if value in normalized:
            return value
    return None


def _write_tools() -> frozenset[str]:
    return frozenset(
        entry.tool_name for entry in load_signed_tool_registry().entries if entry.effect != "READ"
    )


def _state_root() -> Path:
    staging = Path(os.environ["GWA_ATTACHMENT_STAGING_DIR"])
    staging.mkdir(parents=True, exist_ok=True)
    return staging.parent


def _load_state() -> dict[str, object]:
    path = _state_root() / "langgraph-e2e-mcp-state.json"
    if not path.exists():
        return {"counts": {}, "resources": {}}
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _save_state(state: dict[str, object]) -> None:
    path = _state_root() / "langgraph-e2e-mcp-state.json"
    temporary_path = path.with_suffix(f".{os.getpid()}.tmp")
    temporary_path.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    temporary_path.replace(path)


def _append_event(event: dict[str, object]) -> None:
    path = _state_root() / "langgraph-e2e-mcp-events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def _append_runtime_event(event: dict[str, object]) -> None:
    path = _state_root() / "langgraph-e2e-mcp-runtime-events.jsonl"
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(event, sort_keys=True) + "\n")


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


class _ExternalFailure(RuntimeError):
    def __init__(self, code: str, delivery_certainty: str) -> None:
        super().__init__(code)
        self.code = code
        self.delivery_certainty = delivery_certainty


if __name__ == "__main__":
    main()
