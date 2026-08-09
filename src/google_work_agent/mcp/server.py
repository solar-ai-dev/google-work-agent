"""Local MCP child process with fixture-backed Google tools and OAuth provider."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from json import dumps
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlencode, urlparse

from google_work_agent.adapters.mcp.transport import PROTOCOL_VERSION
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import (
    CredentialState,
    OAuthEnvironment,
    ResourceSnapshot,
    ResourceType,
)

REQUIRED_SCOPES = (
    "gmail.readonly",
    "gmail.compose",
    "tasks",
    "calendar.events",
    "calendar.calendarlist.readonly",
    "calendar.events.freebusy",
)
OAUTH_FLOW_TTL_MS = 60_000


@dataclass(frozen=True, slots=True)
class _OAuthFlow:
    flow_id: str
    state: str
    verifier: str
    callback_url: str
    expires_at_ms: int
    client_id: str


class _OAuthConfigurationError(RuntimeError):
    """Raised only when the OAuth entry point lacks required local configuration."""


class _TestKeyring:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def set(self, key: str, value: str) -> None:
        with self._lock:
            payload = self._read()
            payload[key] = value
            self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._read().get(key)

    def delete(self, key: str) -> bool:
        with self._lock:
            payload = self._read()
            existed = key in payload
            payload.pop(key, None)
            self._path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            return existed

    def _read(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        return cast(dict[str, str], json.loads(self._path.read_text(encoding="utf-8")))


class _WorkspaceState:
    def __init__(self) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        self.connection_state = CredentialState.NOT_CONNECTED
        self.account_email: str | None = None
        self.display_name: str | None = None
        self.access_token: str | None = None
        self.last_checked_at_ms = _now_ms()
        self.active_flow: _OAuthFlow | None = None
        self.oauth_settings = GoogleOAuthSettings.load(
            runtime_environment=os.environ.get("GWA_MCP_ENVIRONMENT", ""),
        )
        self.keyring = _TestKeyring(Path(os.environ["GWA_TEST_KEYRING_PATH"]))
        self.resources = _load_resources(Path(os.environ["GWA_PRODUCT_FIXTURE_MANIFEST"]))

    def connection_payload(self) -> dict[str, object]:
        granted_scopes = (
            REQUIRED_SCOPES if self.connection_state is CredentialState.CONNECTED else ()
        )
        return {
            "connected": self.connection_state is CredentialState.CONNECTED,
            "credential_state": self.connection_state.value,
            "account_email": self.account_email,
            "display_name": self.display_name,
            "granted_scopes": list(granted_scopes),
            "missing_scopes": [],
            "reauth_required": self.connection_state is CredentialState.REAUTH_REQUIRED,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "last_checked_at_ms": self.last_checked_at_ms,
        }


def main() -> None:
    state = _WorkspaceState()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        message_type = str(request.get("type"))
        request_id = str(request.get("id", ""))
        if message_type == "shutdown":
            break
        try:
            payload = _dispatch(state, request)
            _write({"id": request_id, "payload": payload})
        except KeyError as error:
            _write(
                {
                    "id": request_id,
                    "error": {"code": "NOT_FOUND", "message": str(error)},
                }
            )
        except _OAuthConfigurationError:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": "Set GOOGLE_OAUTH_CLIENT_ID in .env.local.",
                    },
                }
            )
        except Exception as error:
            _write(
                {
                    "id": request_id,
                    "error": {"code": "MALFORMED_RESPONSE", "message": str(error)},
                }
            )


def _dispatch(state: _WorkspaceState, request: dict[str, object]) -> dict[str, object]:
    message_type = str(request["type"])
    if message_type == "handshake":
        session_key = str(request["session_key"])
        if len(bytes.fromhex(session_key)) < 32:
            raise ValueError("session key must be at least 256 bits")
        state.service_instance_id = str(request["service_instance_id"])
        state.session_key = session_key
        return {"process_instance_id": state.process_instance_id}
    if message_type == "initialize":
        return {
            "protocol_version": PROTOCOL_VERSION,
            "manifest_version": str(request["manifest_version"]),
            "tool_registry_version": str(request["tool_registry_version"]),
        }
    if message_type == "list_tools":
        return {
            "tool_names": sorted(
                entry.tool_name for entry in build_p0_tool_registry().list_entries()
            )
        }
    if message_type == "control_call":
        return _control_call(
            state,
            method=str(request["method"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    if message_type == "tool_call":
        return _tool_call(
            state,
            tool_name=str(request["tool_name"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    raise ValueError(f"unsupported message type: {message_type}")


def _control_call(
    state: _WorkspaceState,
    *,
    method: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    del arguments
    if method == "google.connection.get":
        state.last_checked_at_ms = _now_ms()
        return state.connection_payload()
    if method == "google.connection.disconnect":
        deleted = state.keyring.delete("GoogleWorkAgent/DEVELOPMENT/refresh-token")
        state.connection_state = CredentialState.NOT_CONNECTED
        state.access_token = None
        state.account_email = None
        state.display_name = None
        state.last_checked_at_ms = _now_ms()
        return {
            "disconnected": True,
            "credential_deleted": deleted,
            "revoke_attempted": True,
            "revoke_succeeded": True,
            "credential_state": state.connection_state.value,
        }
    if method == "google.oauth.start":
        if state.oauth_settings.google_oauth_client_id is None:
            raise _OAuthConfigurationError
        if state.active_flow is not None and state.active_flow.expires_at_ms > _now_ms():
            raise ValueError("oauth flow already active")
        flow = _start_oauth_flow(state)
        state.active_flow = flow
        return {
            "flow_id": flow.flow_id,
            "authorization_url": _authorization_url(flow),
            "callback_url": flow.callback_url,
            "expires_at_ms": flow.expires_at_ms,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "scopes": list(REQUIRED_SCOPES),
        }
    raise ValueError(f"unsupported control method: {method}")


def _tool_call(
    state: _WorkspaceState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    if state.connection_state is not CredentialState.CONNECTED:
        raise ValueError("google connection is not ready")
    items = state.resources
    if tool_name == "gmail_search_threads":
        query = str(arguments["query"]).lower()
        threads = [
            item
            for item in items.values()
            if item.resource_type is ResourceType.GMAIL_THREAD
            and (
                query in str(item.payload.get("subject", "")).lower()
                or any(
                    query in str(p).lower()
                    for p in cast(list[object], item.payload.get("participants", []))
                )
            )
        ]
        return {
            "schema_version": "v1",
            "items": [_snapshot_payload(item) for item in threads],
            "next_page_token": None,
        }
    if tool_name == "gmail_get_thread":
        return {
            "schema_version": "v1",
            "item": _snapshot_payload(
                items[(ResourceType.GMAIL_THREAD, str(arguments["thread_id"]))]
            ),
        }
    if tool_name == "gmail_get_message":
        return {
            "schema_version": "v1",
            "item": _snapshot_payload(
                items[(ResourceType.GMAIL_MESSAGE, str(arguments["message_id"]))]
            ),
        }
    if tool_name == "gmail_get_draft":
        return {
            "schema_version": "v1",
            "item": _snapshot_payload(
                items[(ResourceType.GMAIL_DRAFT, str(arguments["draft_id"]))]
            ),
        }
    if tool_name == "tasks_list_tasklists":
        tasklists = [
            item for item in items.values() if item.resource_type is ResourceType.TASK_LIST
        ]
        return {
            "schema_version": "v1",
            "items": [_snapshot_payload(item) for item in tasklists],
            "next_page_token": None,
        }
    if tool_name == "tasks_list_tasks":
        task_list_id = str(arguments["task_list_id"])
        tasks = [
            item
            for item in items.values()
            if item.resource_type is ResourceType.TASK and item.parent_id == task_list_id
        ]
        return {
            "schema_version": "v1",
            "items": [_snapshot_payload(item) for item in tasks],
            "next_page_token": None,
        }
    if tool_name == "tasks_get_task":
        return {
            "schema_version": "v1",
            "item": _snapshot_payload(items[(ResourceType.TASK, str(arguments["task_id"]))]),
        }
    if tool_name == "calendar_list_calendars":
        calendars = [item for item in items.values() if item.resource_type is ResourceType.CALENDAR]
        return {
            "schema_version": "v1",
            "items": [_snapshot_payload(item) for item in calendars],
            "next_page_token": None,
        }
    if tool_name == "calendar_list_events":
        calendar_id = str(arguments["calendar_id"])
        events = [
            item
            for item in items.values()
            if item.resource_type is ResourceType.CALENDAR_EVENT and item.parent_id == calendar_id
        ]
        return {
            "schema_version": "v1",
            "items": [_snapshot_payload(item) for item in events],
            "next_page_token": None,
        }
    if tool_name == "calendar_get_event":
        return {
            "schema_version": "v1",
            "item": _snapshot_payload(
                items[(ResourceType.CALENDAR_EVENT, str(arguments["event_id"]))]
            ),
        }
    if tool_name == "calendar_query_freebusy":
        freebusy_results: list[dict[str, object]] = []
        for calendar_id_item in cast(list[object], arguments["calendar_ids"]):
            freebusy = items[(ResourceType.CALENDAR_FREEBUSY, str(calendar_id_item))]
            freebusy_results.append(
                {
                    "calendar_id": freebusy.resource_id,
                    "intervals": cast(list[dict[str, object]], freebusy.payload["intervals"]),
                }
            )
        return {"schema_version": "v1", "calendars": freebusy_results}
    if tool_name == "search_by_recovery_fingerprint":
        resource_type = ResourceType(str(arguments["resource_type"]))
        fingerprint = str(arguments["recovery_fingerprint"])
        matches = [
            item
            for item in items.values()
            if item.resource_type is resource_type and item.recovery_fingerprint == fingerprint
        ]
        return {"schema_version": "v1", "items": [_snapshot_payload(item) for item in matches]}
    if tool_name in {
        "gmail_create_draft",
        "gmail_update_draft",
        "gmail_send",
        "tasks_create_task",
        "tasks_update_task",
        "calendar_create_event",
        "calendar_update_event",
        "calendar_delete_event",
    }:
        _validate_claim_context(state, tool_name=tool_name, arguments=arguments)
        return {
            "schema_version": "v1",
            "item": _mutate_snapshot(state, tool_name=tool_name, arguments=arguments),
        }
    raise ValueError(f"unsupported tool: {tool_name}")


def _start_oauth_flow(state: _WorkspaceState) -> _OAuthFlow:
    flow_id = f"flow-{secrets.token_hex(8)}"
    oauth_state = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    server = _OAuthCallbackServer(state=state, flow_id=flow_id, expected_state=oauth_state)
    callback_url = server.start()
    expires_at_ms = _now_ms() + OAUTH_FLOW_TTL_MS
    return _OAuthFlow(
        flow_id=flow_id,
        state=oauth_state,
        verifier=verifier,
        callback_url=callback_url,
        expires_at_ms=expires_at_ms,
        client_id=state.oauth_settings.google_oauth_client_id or "",
    )


def _authorization_url(flow: _OAuthFlow) -> str:
    launch_url = f"{flow.callback_url.removesuffix('/callback')}/authorize"
    return f"{launch_url}?{urlencode({'state': flow.state})}"


def _google_authorization_url(flow: _OAuthFlow) -> str:
    query = urlencode(
        {
            "client_id": flow.client_id,
            "redirect_uri": flow.callback_url,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES),
            "state": flow.state,
            "code_challenge_method": "S256",
            "code_challenge": hashlib.sha256(flow.verifier.encode("utf-8")).hexdigest(),
        }
    )
    return f"https://accounts.google.test/o/oauth2/v2/auth?{query}"


class _OAuthCallbackServer:
    def __init__(self, *, state: _WorkspaceState, flow_id: str, expected_state: str) -> None:
        self._state = state
        self._flow_id = flow_id
        self._expected_state = expected_state
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    def _handler(self) -> type[BaseHTTPRequestHandler]:
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                params = parse_qs(parsed.query)
                state_value = params.get("state", [""])[0]
                if parsed.path == "/oauth/authorize":
                    flow = outer._state.active_flow
                    if flow is None or not hmac.compare_digest(state_value, outer._expected_state):
                        self.send_response(400)
                        self.end_headers()
                        self.wfile.write(b"state mismatch")
                        return
                    self.send_response(302)
                    self.send_header("Location", _google_authorization_url(flow))
                    self.end_headers()
                    return
                code = params.get("code", [""])[0]
                if not hmac.compare_digest(state_value, outer._expected_state):
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b"state mismatch")
                    return
                outer._state.keyring.set(
                    "GoogleWorkAgent/DEVELOPMENT/refresh-token",
                    f"refresh::{code}",
                )
                outer._state.access_token = f"access::{code}"
                outer._state.connection_state = CredentialState.CONNECTED
                outer._state.account_email = "user@example.com"
                outer._state.display_name = "User"
                outer._state.last_checked_at_ms = _now_ms()
                outer._state.active_flow = None
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"connected")
                threading.Thread(target=outer._server.shutdown, daemon=True).start()

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                del format, args

        return Handler

    def start(self) -> str:
        self._thread.start()
        port = self._server.server_port
        return f"http://127.0.0.1:{port}/oauth/callback"


def _validate_claim_context(
    state: _WorkspaceState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> None:
    claim_context = cast(dict[str, object] | None, arguments.get("claim_context"))
    if claim_context is None:
        raise ValueError("claim context required")
    if str(claim_context["tool_name"]) != tool_name:
        raise ValueError("claim tool mismatch")
    if str(claim_context["service_instance_id"]) != state.service_instance_id:
        raise ValueError("claim service binding mismatch")
    if str(claim_context["mcp_process_instance_id"]) != state.process_instance_id:
        raise ValueError("claim process binding mismatch")
    if _now_ms() >= int(str(claim_context["expires_at_ms"])):
        raise ValueError("claim expired")
    canonical_arguments = {
        key: value
        for key, value in arguments.items()
        if key not in {"claim_context", "recovery_fingerprint"}
    }
    canonical_hash = hashlib.sha256(
        dumps(canonical_arguments, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if canonical_hash != str(claim_context["canonical_arguments_hash"]):
        raise ValueError("claim arguments mismatch")
    signature_payload = dumps(
        {
            "action_id": claim_context["action_id"],
            "approval_id": claim_context["approval_id"],
            "execution_attempt_id": claim_context["execution_attempt_id"],
            "tool_name": claim_context["tool_name"],
            "canonical_arguments_hash": claim_context["canonical_arguments_hash"],
            "service_instance_id": claim_context["service_instance_id"],
            "mcp_process_instance_id": claim_context["mcp_process_instance_id"],
            "expires_at_ms": claim_context["expires_at_ms"],
            "nonce": claim_context["nonce"],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    expected = hmac.new(
        bytes.fromhex(state.session_key or ""),
        signature_payload,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, str(claim_context["signature"])):
        raise ValueError("claim signature mismatch")


def _mutate_snapshot(
    state: _WorkspaceState,
    *,
    tool_name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    items = state.resources
    if tool_name == "gmail_send":
        draft_id = str(arguments["draft_id"])
        draft = items[(ResourceType.GMAIL_DRAFT, draft_id)]
        payload = dict(draft.payload)
        payload["draft_id"] = draft_id
        payload["sent"] = True
        payload["recovery_fingerprint"] = arguments.get("recovery_fingerprint")
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="mcp-runtime",
            resource_type=ResourceType.GMAIL_MESSAGE,
            resource_id=f"sent-{draft_id}",
            parent_id=draft.parent_id,
            related_resource_ids=draft.related_resource_ids,
            version="1",
            recovery_fingerprint=_optional_string(arguments.get("recovery_fingerprint")),
            payload=payload,
        )
        items[(snapshot.resource_type, snapshot.resource_id)] = snapshot
        return _snapshot_payload(snapshot)
    if tool_name == "calendar_delete_event":
        if arguments.get("delete_scope") not in {None, "SINGLE"}:
            raise ValueError("recurring event series deletion is forbidden")
        calendar_id = str(arguments["calendar_id"])
        event_id = str(arguments["event_id"])
        key = (ResourceType.CALENDAR_EVENT, event_id)
        event = items[key]
        if event.parent_id != calendar_id:
            raise ValueError("calendar event parent mismatch")
        del items[key]
        tombstone = ResourceSnapshot(
            fixture_snapshot_id=event.fixture_snapshot_id,
            resource_type=event.resource_type,
            resource_id=event.resource_id,
            parent_id=event.parent_id,
            related_resource_ids=event.related_resource_ids,
            version=event.version,
            recovery_fingerprint=event.recovery_fingerprint,
            payload={"deleted": True},
        )
        return _snapshot_payload(tombstone)
    payload = cast(dict[str, object], arguments["payload"])
    if tool_name == "tasks_create_task":
        resource_id = str(payload.get("resource_id", f"task-{secrets.token_hex(4)}"))
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="mcp-runtime",
            resource_type=ResourceType.TASK,
            resource_id=resource_id,
            parent_id=str(arguments["task_list_id"]),
            related_resource_ids=(str(arguments["task_list_id"]),),
            version="1",
            recovery_fingerprint=_optional_string(payload.get("recovery_fingerprint")),
            payload=payload,
        )
        items[(snapshot.resource_type, snapshot.resource_id)] = snapshot
        return _snapshot_payload(snapshot)
    if tool_name == "tasks_update_task":
        key = (ResourceType.TASK, str(arguments["task_id"]))
        current = items[key]
        updated_payload = dict(current.payload)
        updated_payload.update(payload)
        updated = ResourceSnapshot(
            fixture_snapshot_id=current.fixture_snapshot_id,
            resource_type=current.resource_type,
            resource_id=current.resource_id,
            parent_id=current.parent_id,
            related_resource_ids=current.related_resource_ids,
            version=str(int(current.version) + 1),
            recovery_fingerprint=current.recovery_fingerprint,
            payload=updated_payload,
        )
        items[key] = updated
        return _snapshot_payload(updated)
    if tool_name == "gmail_create_draft":
        resource_id = str(payload.get("resource_id", f"draft-{secrets.token_hex(4)}"))
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="mcp-runtime",
            resource_type=ResourceType.GMAIL_DRAFT,
            resource_id=resource_id,
            parent_id=None,
            related_resource_ids=(),
            version="1",
            recovery_fingerprint=_optional_string(payload.get("recovery_fingerprint")),
            payload=payload,
        )
        items[(snapshot.resource_type, snapshot.resource_id)] = snapshot
        return _snapshot_payload(snapshot)
    if tool_name == "gmail_update_draft":
        key = (ResourceType.GMAIL_DRAFT, str(arguments["draft_id"]))
        current = items[key]
        updated_payload = dict(current.payload)
        updated_payload.update(payload)
        updated = ResourceSnapshot(
            fixture_snapshot_id=current.fixture_snapshot_id,
            resource_type=current.resource_type,
            resource_id=current.resource_id,
            parent_id=current.parent_id,
            related_resource_ids=current.related_resource_ids,
            version=str(int(current.version) + 1),
            recovery_fingerprint=current.recovery_fingerprint,
            payload=updated_payload,
        )
        items[key] = updated
        return _snapshot_payload(updated)
    calendar_id = str(arguments.get("calendar_id", "calendar-primary"))
    if tool_name == "calendar_create_event":
        resource_id = str(payload.get("resource_id", f"event-{secrets.token_hex(4)}"))
        snapshot = ResourceSnapshot(
            fixture_snapshot_id="mcp-runtime",
            resource_type=ResourceType.CALENDAR_EVENT,
            resource_id=resource_id,
            parent_id=calendar_id,
            related_resource_ids=(calendar_id,),
            version="1",
            recovery_fingerprint=_optional_string(payload.get("recovery_fingerprint")),
            payload=payload,
        )
        items[(snapshot.resource_type, snapshot.resource_id)] = snapshot
        return _snapshot_payload(snapshot)
    if tool_name == "calendar_update_event":
        key = (ResourceType.CALENDAR_EVENT, str(arguments["event_id"]))
        current = items[key]
        updated_payload = dict(current.payload)
        updated_payload.update(payload)
        updated = ResourceSnapshot(
            fixture_snapshot_id=current.fixture_snapshot_id,
            resource_type=current.resource_type,
            resource_id=current.resource_id,
            parent_id=current.parent_id,
            related_resource_ids=current.related_resource_ids,
            version=str(int(current.version) + 1),
            recovery_fingerprint=current.recovery_fingerprint,
            payload=updated_payload,
        )
        items[key] = updated
        return _snapshot_payload(updated)
    raise ValueError(f"unsupported mutating tool: {tool_name}")


def _snapshot_payload(snapshot: ResourceSnapshot) -> dict[str, object]:
    return {
        "fixture_snapshot_id": snapshot.fixture_snapshot_id,
        "resource_type": snapshot.resource_type.value,
        "resource_id": snapshot.resource_id,
        "parent_id": snapshot.parent_id,
        "related_resource_ids": list(snapshot.related_resource_ids),
        "version": snapshot.version,
        "recovery_fingerprint": snapshot.recovery_fingerprint,
        "payload": snapshot.payload,
    }


def _load_resources(manifest_path: Path) -> dict[tuple[ResourceType, str], ResourceSnapshot]:
    manifest = cast(dict[str, object], json.loads(manifest_path.read_text(encoding="utf-8")))
    base_dir = manifest_path.parent
    resources: dict[tuple[ResourceType, str], ResourceSnapshot] = {}
    for entry in cast(list[dict[str, object]], manifest["resources"]):
        payload = cast(
            dict[str, object],
            json.loads((base_dir / str(entry["path"])).read_text(encoding="utf-8")),
        )
        snapshot = ResourceSnapshot(
            fixture_snapshot_id=str(manifest["snapshot_id"]),
            resource_type=ResourceType(str(payload["resource_type"])),
            resource_id=str(payload["resource_id"]),
            parent_id=_optional_string(payload.get("parent_id")),
            related_resource_ids=tuple(
                str(item) for item in cast(list[object], payload["related_resource_ids"])
            ),
            version=str(payload["version"]),
            recovery_fingerprint=_optional_string(payload.get("recovery_fingerprint")),
            payload=cast(dict[str, object], payload["payload"]),
        )
        resources[(snapshot.resource_type, snapshot.resource_id)] = snapshot
    return resources


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    main()
