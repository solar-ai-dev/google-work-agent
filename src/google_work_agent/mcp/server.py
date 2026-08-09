"""Local MCP child process for Google OAuth credentials and read tools."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.mcp.transport import PROTOCOL_VERSION
from google_work_agent.domain import build_p0_tool_registry
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import CredentialState, OAuthEnvironment, SecretStore, TimeRange

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_KEYRING_SERVICE = "GoogleWorkAgent/DEVELOPMENT"
GOOGLE_REFRESH_TOKEN_ACCOUNT = "google-oauth-refresh-token"
REQUIRED_SCOPES = (
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/tasks",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
)
OAUTH_FLOW_TTL_MS = 60_000
DEFAULT_ACCESS_TOKEN_TTL_MS = 3_600_000
GOOGLE_API_TIMEOUT_SECONDS = 30


@dataclass(frozen=True, slots=True)
class _OAuthFlow:
    flow_id: str
    state: str
    verifier: str
    callback_url: str
    expires_at_ms: int
    client_id: str


class _OAuthConfigurationError(RuntimeError):
    """Raised when local OAuth configuration is incomplete."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class _OAuthExchangeError(RuntimeError):
    """Raised when Google's token endpoint rejects a callback code."""

    def __init__(
        self,
        safe_error_code: str = "TOKEN_EXCHANGE_FAILED",
        safe_error_description: str | None = None,
    ) -> None:
        super().__init__(safe_error_code)
        self.safe_error_code = safe_error_code
        self.safe_error_description = safe_error_description


class _OAuthReauthenticationRequired(RuntimeError):
    """Raised when Google rejects a stored refresh token."""


class _WorkspaceToolError(RuntimeError):
    """A sanitized Google Workspace read failure."""

    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


class _WorkspaceState:
    def __init__(self, *, keyring: SecretStore | None = None) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        self.connection_state = CredentialState.NOT_CONNECTED
        self.account_email: str | None = None
        self.display_name: str | None = None
        # Access tokens are intentionally process-memory-only.
        self.access_token: str | None = None
        self.access_token_expires_at_ms = 0
        self._refresh_lock = threading.Lock()
        self._oauth_flow_lock = threading.Lock()
        self.last_checked_at_ms = _now_ms()
        self.last_oauth_error_code: str | None = None
        self.last_oauth_error_description: str | None = None
        self.active_flow: _OAuthFlow | None = None
        self.oauth_settings = GoogleOAuthSettings.load(
            runtime_environment=os.environ.get("GWA_MCP_ENVIRONMENT", ""),
        )
        self.keyring = keyring or _credential_store_from_environment()
        if (
            self.keyring.get_secret(
                service=GOOGLE_KEYRING_SERVICE,
                account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
            )
            is not None
        ):
            self.connection_state = CredentialState.CONNECTED

    def connection_payload(self) -> dict[str, object]:
        connected = self.connection_state is CredentialState.CONNECTED
        return {
            "connected": connected,
            "credential_state": self.connection_state.value,
            "account_email": self.account_email,
            "display_name": self.display_name,
            "granted_scopes": list(REQUIRED_SCOPES) if connected else [],
            "missing_scopes": [],
            "reauth_required": self.connection_state is CredentialState.REAUTH_REQUIRED,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "last_checked_at_ms": self.last_checked_at_ms,
            "safe_error_code": self.last_oauth_error_code,
            "safe_error_description": self.last_oauth_error_description,
        }

    def ensure_access_token(self) -> None:
        if self.access_token is not None and _now_ms() < self.access_token_expires_at_ms:
            return
        with self._refresh_lock:
            if self.access_token is not None and _now_ms() < self.access_token_expires_at_ms:
                return
            refresh_token = self.keyring.get_secret(
                service=GOOGLE_KEYRING_SERVICE,
                account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
            )
            if refresh_token is None:
                self.connection_state = CredentialState.NOT_CONNECTED
                return
            access_token, expires_at_ms, rotated_refresh_token = _refresh_access_token(
                refresh_token,
                self.oauth_settings.google_oauth_client_id,
                self.oauth_settings.google_oauth_client_secret,
            )
            self.access_token = access_token
            self.access_token_expires_at_ms = expires_at_ms
            if rotated_refresh_token is not None:
                self.keyring.set_secret(
                    service=GOOGLE_KEYRING_SERVICE,
                    account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
                    secret=rotated_refresh_token,
                )
            self.connection_state = CredentialState.CONNECTED


def main() -> None:
    try:
        state = _WorkspaceState()
    except RuntimeError:
        # Do not disclose keyring implementation details or credential material.
        state = None
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        request = cast(dict[str, object], json.loads(line))
        request_id = str(request.get("id", ""))
        if str(request.get("type")) == "shutdown":
            break
        if state is None:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": "OS keyring is unavailable.",
                    },
                }
            )
            continue
        try:
            _write({"id": request_id, "payload": _dispatch(state, request)})
        except _OAuthConfigurationError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "CONFIGURATION_ERROR",
                        "message": error.safe_code,
                    },
                }
            )
        except _OAuthExchangeError:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": "Google OAuth token exchange failed.",
                    },
                }
            )
        except _WorkspaceToolError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "TOOL_REJECTED",
                        "message": error.safe_code,
                    },
                }
            )
        except KeyError as error:
            _write({"id": request_id, "error": {"code": "NOT_FOUND", "message": str(error)}})
        except Exception:
            _write(
                {
                    "id": request_id,
                    "error": {"code": "MALFORMED_RESPONSE", "message": "MCP request failed."},
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
        return _control_call(state, method=str(request["method"]))
    if message_type == "tool_call":
        return _tool_call(
            state,
            tool_name=str(request["tool_name"]),
            arguments=cast(dict[str, object], request["arguments"]),
        )
    raise ValueError("unsupported message type")


def _tool_call(
    state: _WorkspaceState, *, tool_name: str, arguments: dict[str, object]
) -> dict[str, object]:
    read_tools = {
        "gmail_search_threads": _gmail_search_threads,
        "gmail_get_thread": _gmail_get_thread,
        "gmail_get_message": _gmail_get_message,
        "tasks_list_tasklists": _tasks_list_tasklists,
        "tasks_list_tasks": _tasks_list_tasks,
        "tasks_get_task": _tasks_get_task,
        "calendar_list_calendars": _calendar_list_calendars,
        "calendar_list_events": _calendar_list_events,
        "calendar_get_event": _calendar_get_event,
        "calendar_query_freebusy": _calendar_query_freebusy,
    }
    handler = read_tools.get(tool_name)
    if handler is None:
        raise _WorkspaceToolError("TOOL_NOT_AVAILABLE")
    return handler(state, arguments)


def _gmail_search_threads(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    query = _text_argument(arguments, "query", maximum=2048, allow_empty=True)
    params = _page_params(arguments)
    if query:
        params["q"] = query
    payload = _google_api(state, "https://gmail.googleapis.com/gmail/v1/users/me/threads", params)
    items = []
    for thread in _object_list(payload.get("threads")):
        thread_id = _required_response_text(thread, "id")
        items.append(
            _snapshot(
                "gmail_thread",
                thread_id,
                None,
                (),
                thread.get("historyId"),
                {"snippet": _optional_text(thread.get("snippet"))},
            )
        )
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _gmail_get_thread(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    thread_id = _text_argument(arguments, "thread_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id, safe='')}",
        {"format": "metadata"},
    )
    messages = _object_list(payload.get("messages"))
    headers = _headers(messages[0]) if messages else {}
    message_ids = tuple(_required_response_text(item, "id") for item in messages)
    participants = tuple(value for value in (headers.get("from"), headers.get("to")) if value)
    return {
        "item": _snapshot(
            "gmail_thread",
            thread_id,
            None,
            message_ids,
            payload.get("historyId"),
            {
                "subject": headers.get("subject", thread_id),
                "snippet": _optional_text(payload.get("snippet")),
                "participants": list(participants),
                "message_ids": list(message_ids),
            },
        )
    }


def _gmail_get_message(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    message_id = _text_argument(arguments, "message_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id, safe='')}",
        {"format": "metadata"},
    )
    headers = _headers(payload)
    return {
        "item": _snapshot(
            "gmail_message",
            message_id,
            _optional_text(payload.get("threadId")),
            (),
            payload.get("historyId"),
            {
                "subject": headers.get("subject", message_id),
                "snippet": _optional_text(payload.get("snippet")),
                "from": headers.get("from"),
                "to": headers.get("to"),
                "received_at": headers.get("date"),
            },
        )
    }


def _tasks_list_tasklists(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    payload = _google_api(
        state, "https://tasks.googleapis.com/tasks/v1/users/@me/lists", _page_params(arguments)
    )
    items = [
        _snapshot(
            "task_list",
            _required_response_text(item, "id"),
            None,
            (),
            item.get("updated"),
            {
                "title": _optional_text(item.get("title")) or _required_response_text(item, "id"),
                "kind": _optional_text(item.get("kind")),
            },
        )
        for item in _object_list(payload.get("items"))
    ]
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _tasks_list_tasks(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    task_list_id = _text_argument(arguments, "task_list_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://tasks.googleapis.com/tasks/v1/lists/{quote(task_list_id, safe='')}/tasks",
        _page_params(arguments),
    )
    items = [_task_snapshot(item, task_list_id) for item in _object_list(payload.get("items"))]
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _tasks_get_task(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    task_list_id = _text_argument(arguments, "task_list_id", maximum=2048)
    task_id = _text_argument(arguments, "task_id", maximum=2048)
    task_list_path = quote(task_list_id, safe="")
    task_path = quote(task_id, safe="")
    payload = _google_api(
        state,
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}",
    )
    return {"item": _task_snapshot(payload, task_list_id)}


def _calendar_list_calendars(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    payload = _google_api(
        state,
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        _page_params(arguments),
    )
    items = [
        _snapshot(
            "calendar",
            _required_response_text(item, "id"),
            None,
            (),
            item.get("etag"),
            {
                "summary": _optional_text(item.get("summary"))
                or _required_response_text(item, "id"),
                "time_zone": _optional_text(item.get("timeZone")),
            },
        )
        for item in _object_list(payload.get("items"))
    ]
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _calendar_list_events(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = _text_argument(arguments, "calendar_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
        _page_params(arguments),
    )
    items = [_event_snapshot(item, calendar_id) for item in _object_list(payload.get("items"))]
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _calendar_get_event(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    calendar_id = _text_argument(arguments, "calendar_id", maximum=2048)
    event_id = _text_argument(arguments, "event_id", maximum=2048)
    calendar_path = quote(calendar_id, safe="")
    event_path = quote(event_id, safe="")
    payload = _google_api(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
    )
    return {"item": _event_snapshot(payload, calendar_id)}


def _calendar_query_freebusy(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_ids = _calendar_ids_argument(arguments)
    try:
        time_range = TimeRange(
            start=_text_argument(arguments, "time_min", maximum=2048),
            end=_text_argument(arguments, "time_max", maximum=2048),
        )
    except ValueError as error:
        raise _WorkspaceToolError("INVALID_ARGUMENT") from error
    payload = _google_api_post(
        state,
        "https://www.googleapis.com/calendar/v3/freeBusy",
        {
            "timeMin": time_range.start,
            "timeMax": time_range.end,
            "items": [{"id": calendar_id} for calendar_id in calendar_ids],
        },
    )
    calendars = cast(dict[str, object], payload.get("calendars") or {})
    return {
        "calendars": [
            {
                "calendar_id": calendar_id,
                "intervals": [
                    {
                        "start": _required_response_text(interval, "start"),
                        "end": _required_response_text(interval, "end"),
                        "transparency": "busy",
                    }
                    for interval in _object_list(
                        cast(dict[str, object], calendars.get(calendar_id) or {}).get("busy")
                    )
                ],
            }
            for calendar_id in calendar_ids
        ]
    }


def _task_snapshot(item: dict[str, object], task_list_id: str) -> dict[str, object]:
    task_id = _required_response_text(item, "id")
    return _snapshot(
        "task",
        task_id,
        task_list_id,
        (task_list_id,),
        item.get("updated"),
        {
            "title": _optional_text(item.get("title")) or task_id,
            "notes": _optional_text(item.get("notes")),
            "due": _optional_text(item.get("due")),
            "status": _optional_text(item.get("status")),
        },
    )


def _event_snapshot(item: dict[str, object], calendar_id: str) -> dict[str, object]:
    event_id = _required_response_text(item, "id")
    start = cast(dict[str, object], item.get("start") or {})
    end = cast(dict[str, object], item.get("end") or {})
    return _snapshot(
        "calendar_event",
        event_id,
        calendar_id,
        (calendar_id,),
        item.get("etag"),
        {
            "title": _optional_text(item.get("summary")) or event_id,
            "status": _optional_text(item.get("status")),
            "transparency": _optional_text(item.get("transparency")),
            "event_kind": _optional_text(item.get("eventType")),
            "start": _optional_text(start.get("dateTime")) or _optional_text(start.get("date")),
            "end": _optional_text(end.get("dateTime")) or _optional_text(end.get("date")),
        },
    )


def _snapshot(
    resource_type: str,
    resource_id: str,
    parent_id: str | None,
    related_resource_ids: tuple[str, ...],
    version: object,
    payload: dict[str, object],
) -> dict[str, object]:
    return {
        "fixture_snapshot_id": resource_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "parent_id": parent_id,
        "related_resource_ids": list(related_resource_ids),
        "version": _optional_text(version) or "",
        "recovery_fingerprint": None,
        "payload": {key: value for key, value in payload.items() if value is not None},
    }


def _page_params(arguments: dict[str, object]) -> dict[str, str]:
    page_size = arguments.get("page_size", 20)
    if not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    params = {"maxResults": str(page_size)}
    page_token = arguments.get("page_token")
    if page_token is not None:
        params["pageToken"] = _text_value(page_token, maximum=2048)
    return params


def _text_argument(
    arguments: dict[str, object], name: str, *, maximum: int, allow_empty: bool = False
) -> str:
    if name not in arguments:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    value = _text_value(arguments[name], maximum=maximum)
    if not value and not allow_empty:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return value


def _text_value(value: object, *, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(char) < 32 for char in value):
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return value


def _calendar_ids_argument(arguments: dict[str, object]) -> tuple[str, ...]:
    value = arguments.get("calendar_ids")
    if not isinstance(value, list) or not 1 <= len(value) <= 20:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return tuple(_text_value(item, maximum=2048) for item in value)


def _google_api(
    state: _WorkspaceState, url: str, params: dict[str, str] | None = None
) -> dict[str, object]:
    try:
        state.ensure_access_token()
    except _OAuthReauthenticationRequired as error:
        state.connection_state = CredentialState.REAUTH_REQUIRED
        raise _WorkspaceToolError("REAUTH_REQUIRED") from error
    if state.access_token is None:
        raise _WorkspaceToolError("OAUTH_NOT_CONNECTED")
    request_url = f"{url}?{urlencode(params)}" if params else url
    request = Request(
        request_url,
        headers={"Authorization": f"Bearer {state.access_token}", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=GOOGLE_API_TIMEOUT_SECONDS) as response:  # nosec B310: fixed Google API endpoints
            return cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        codes = {
            401: "REAUTH_REQUIRED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            429: "RATE_LIMITED",
        }
        if error.code == 401:
            state.connection_state = CredentialState.REAUTH_REQUIRED
            state.access_token = None
            state.access_token_expires_at_ms = 0
        raise _WorkspaceToolError(
            codes.get(error.code, "UPSTREAM_5XX" if error.code >= 500 else "GOOGLE_REQUEST_FAILED")
        ) from error
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _WorkspaceToolError(
            "TIMEOUT" if isinstance(error, TimeoutError) else "MCP_UNAVAILABLE"
        ) from error


def _google_api_post(
    state: _WorkspaceState, url: str, body: dict[str, object]
) -> dict[str, object]:
    try:
        state.ensure_access_token()
    except _OAuthReauthenticationRequired as error:
        state.connection_state = CredentialState.REAUTH_REQUIRED
        raise _WorkspaceToolError("REAUTH_REQUIRED") from error
    if state.access_token is None:
        raise _WorkspaceToolError("OAUTH_NOT_CONNECTED")
    request = Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {state.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=GOOGLE_API_TIMEOUT_SECONDS) as response:  # nosec B310: fixed Google API endpoint
            return cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        codes = {
            401: "REAUTH_REQUIRED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            429: "RATE_LIMITED",
        }
        if error.code == 401:
            state.connection_state = CredentialState.REAUTH_REQUIRED
            state.access_token = None
            state.access_token_expires_at_ms = 0
        raise _WorkspaceToolError(
            codes.get(error.code, "UPSTREAM_5XX" if error.code >= 500 else "GOOGLE_REQUEST_FAILED")
        ) from error
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _WorkspaceToolError(
            "TIMEOUT" if isinstance(error, TimeoutError) else "MCP_UNAVAILABLE"
        ) from error


def _credential_store_from_environment() -> SecretStore:
    test_keyring_path = os.environ.get("GWA_TEST_KEYRING_PATH")
    if test_keyring_path:
        return _TestFileSecretStore(Path(test_keyring_path))
    return OSKeyringSecretStore()


class _TestFileSecretStore(SecretStore):
    """Test-only cross-process store selected by an explicit test environment variable."""

    def __init__(self, path: Path) -> None:
        self._path = path

    def set_secret(self, *, service: str, account: str, secret: str) -> None:
        values = self._read()
        values[f"{service}:{account}"] = secret
        self._write(values)

    def get_secret(self, *, service: str, account: str) -> str | None:
        return self._read().get(f"{service}:{account}")

    def delete_secret(self, *, service: str, account: str) -> bool:
        values = self._read()
        removed = values.pop(f"{service}:{account}", None) is not None
        self._write(values)
        return removed

    def _read(self) -> dict[str, str]:
        if not self._path.is_file():
            return {}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return {str(key): str(value) for key, value in cast(dict[str, object], payload).items()}

    def _write(self, values: dict[str, str]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(values, sort_keys=True), encoding="utf-8")


def _object_list(value: object) -> list[dict[str, object]]:
    return (
        [cast(dict[str, object], item) for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _required_response_text(payload: dict[str, object], name: str) -> str:
    value = _optional_text(payload.get(name))
    if value is None:
        raise _WorkspaceToolError("INVALID_MCP_OUTPUT")
    return value


def _optional_text(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _headers(message: dict[str, object]) -> dict[str, str]:
    payload = cast(dict[str, object], message.get("payload") or {})
    return {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in _object_list(payload.get("headers"))
        if item.get("name") and item.get("value")
    }


def _control_call(state: _WorkspaceState, *, method: str) -> dict[str, object]:
    if method == "google.connection.get":
        try:
            state.ensure_access_token()
        except _OAuthReauthenticationRequired:
            state.connection_state = CredentialState.REAUTH_REQUIRED
            state.access_token = None
            state.access_token_expires_at_ms = 0
        state.last_checked_at_ms = _now_ms()
        return state.connection_payload()
    if method == "google.connection.disconnect":
        refresh_token = state.keyring.get_secret(
            service=GOOGLE_KEYRING_SERVICE,
            account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
        )
        revoke_succeeded = (
            _revoke_refresh_token(refresh_token) if refresh_token is not None else False
        )
        deleted = state.keyring.delete_secret(
            service=GOOGLE_KEYRING_SERVICE, account=GOOGLE_REFRESH_TOKEN_ACCOUNT
        )
        state.connection_state = CredentialState.NOT_CONNECTED
        state.access_token = None
        state.access_token_expires_at_ms = 0
        state.account_email = None
        state.display_name = None
        state.last_checked_at_ms = _now_ms()
        return {
            "disconnected": True,
            "credential_deleted": deleted,
            "revoke_attempted": refresh_token is not None,
            "revoke_succeeded": revoke_succeeded,
            "credential_state": state.connection_state.value,
        }
    if method == "google.oauth.start":
        if state.oauth_settings.google_oauth_client_id is None:
            raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
        if state.oauth_settings.google_oauth_client_secret is None:
            raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
        if state.active_flow is not None and state.active_flow.expires_at_ms > _now_ms():
            raise ValueError("oauth flow already active")
        flow = _start_oauth_flow(state)
        state.last_oauth_error_code = None
        state.last_oauth_error_description = None
        state.active_flow = flow
        return {
            "flow_id": flow.flow_id,
            "authorization_url": _authorization_url(flow),
            "callback_url": flow.callback_url,
            "expires_at_ms": flow.expires_at_ms,
            "oauth_environment": OAuthEnvironment.DEVELOPMENT.value,
            "scopes": list(REQUIRED_SCOPES),
        }
    raise ValueError("unsupported control method")


def _start_oauth_flow(state: _WorkspaceState) -> _OAuthFlow:
    oauth_state = secrets.token_urlsafe(24)
    server = _OAuthCallbackServer(state=state, expected_state=oauth_state)
    callback_url = server.start()
    return _OAuthFlow(
        flow_id=f"flow-{secrets.token_hex(8)}",
        state=oauth_state,
        verifier=secrets.token_urlsafe(48),
        callback_url=callback_url,
        expires_at_ms=_now_ms() + OAUTH_FLOW_TTL_MS,
        client_id=state.oauth_settings.google_oauth_client_id or "",
    )


def _authorization_url(flow: _OAuthFlow) -> str:
    # The API returns only a loopback URL.  The client ID is never sent in an API payload.
    parsed = urlparse(flow.callback_url)
    loopback_origin = f"{parsed.scheme}://{parsed.netloc}"
    return f"{loopback_origin}/oauth/authorize?{urlencode({'state': flow.state})}"


def _pkce_s256(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _google_authorization_url(flow: _OAuthFlow) -> str:
    query = urlencode(
        {
            "client_id": flow.client_id,
            "redirect_uri": flow.callback_url,
            "response_type": "code",
            "scope": " ".join(REQUIRED_SCOPES),
            "state": flow.state,
            "code_challenge_method": "S256",
            "code_challenge": _pkce_s256(flow.verifier),
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    return f"{GOOGLE_AUTHORIZATION_ENDPOINT}?{query}"


def _exchange_authorization_code(
    flow: _OAuthFlow,
    code: str,
    client_secret: str | None,
) -> tuple[str, str | None]:
    if client_secret is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
    body = urlencode(
        {
            "client_id": flow.client_id,
            "client_secret": client_secret,
            "code": code,
            "code_verifier": flow.verifier,
            "grant_type": "authorization_code",
            "redirect_uri": flow.callback_url,
        }
    ).encode("ascii")
    request = Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google endpoint
            payload = cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        raise _oauth_exchange_error_from_http_error(
            error,
            sensitive_values=(
                flow.client_id,
                client_secret,
                code,
                flow.verifier,
                flow.state,
                flow.callback_url,
            ),
        ) from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise _OAuthExchangeError from error
    refresh_token = payload.get("refresh_token")
    if not isinstance(refresh_token, str) or not refresh_token.strip():
        raise _OAuthExchangeError
    access_token = payload.get("access_token")
    return refresh_token, access_token if isinstance(access_token, str) else None


def _oauth_exchange_error_from_http_error(
    error: HTTPError,
    *,
    sensitive_values: tuple[str, ...],
) -> _OAuthExchangeError:
    try:
        payload = cast(dict[str, object], json.loads(error.read().decode("utf-8")))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return _OAuthExchangeError(f"TOKEN_EXCHANGE_HTTP_{error.code}")
    provider_error = payload.get("error")
    safe_description = _redact_provider_error_description(
        payload.get("error_description"),
        sensitive_values=sensitive_values,
    )
    if provider_error == "invalid_grant":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_GRANT",
            safe_description
            or "Google rejected the authorization code or its PKCE/redirect binding.",
        )
    if provider_error == "invalid_client":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_CLIENT",
            safe_description or "Google rejected the configured desktop OAuth client.",
        )
    if provider_error == "redirect_uri_mismatch":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_REDIRECT_URI_MISMATCH",
            safe_description or "Google rejected the loopback redirect URI binding.",
        )
    if provider_error == "invalid_request":
        return _OAuthExchangeError(
            "TOKEN_EXCHANGE_INVALID_REQUEST",
            safe_description or "Google rejected the token request.",
        )
    return _OAuthExchangeError(f"TOKEN_EXCHANGE_HTTP_{error.code}", safe_description)


def _redact_provider_error_description(
    value: object, *, sensitive_values: tuple[str, ...]
) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    redacted = value
    for sensitive_value in sensitive_values:
        if sensitive_value:
            redacted = redacted.replace(sensitive_value, "[REDACTED]")
    redacted = re.sub(
        r"(?i)\b(code|token|verifier|state|secret)=([^\s&,]+)",
        r"\1=[REDACTED]",
        redacted,
    )
    normalized = " ".join(redacted.split())
    return normalized[:240] or None


def _refresh_access_token(
    refresh_token: str,
    client_id: str | None,
    client_secret: str | None,
) -> tuple[str, int, str | None]:
    if client_id is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
    if client_secret is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_SECRET_MISSING")
    body = urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
    ).encode("ascii")
    request = Request(
        GOOGLE_TOKEN_ENDPOINT,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google endpoint
            payload = cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        if error.code == 400:
            raise _OAuthReauthenticationRequired from error
        raise _OAuthExchangeError from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        raise _OAuthExchangeError from error
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise _OAuthExchangeError
    expires_in = payload.get("expires_in")
    ttl_ms = int(expires_in) * 1000 if isinstance(expires_in, int) else DEFAULT_ACCESS_TOKEN_TTL_MS
    rotated = payload.get("refresh_token")
    return access_token, _now_ms() + ttl_ms, rotated if isinstance(rotated, str) else None


def _revoke_refresh_token(refresh_token: str) -> bool:
    request = Request(
        GOOGLE_REVOKE_ENDPOINT,
        data=urlencode({"token": refresh_token}).encode("ascii"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=10):  # nosec B310: fixed Google endpoint
            return True
    except (HTTPError, URLError, TimeoutError):
        return False


class _OAuthCallbackServer:
    def __init__(self, *, state: _WorkspaceState, expected_state: str) -> None:
        self._state = state
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
                if not hmac.compare_digest(state_value, outer._expected_state):
                    self._respond(400, b"state mismatch")
                    outer._finish_flow()
                    return
                if parsed.path == "/oauth/authorize":
                    flow = outer._state.active_flow
                    if flow is None:
                        self._respond(400, b"oauth flow unavailable")
                        outer._finish_flow()
                        return
                    self.send_response(302)
                    self.send_header("Location", _google_authorization_url(flow))
                    self.end_headers()
                    return
                if parsed.path != "/oauth/callback":
                    self._respond(404, b"not found")
                    outer._finish_flow()
                    return
                code = params.get("code", [""])[0]
                with outer._state._oauth_flow_lock:
                    flow = outer._state.active_flow
                    if code and flow is not None and flow.expires_at_ms > _now_ms():
                        outer._state.active_flow = None
                    else:
                        flow = None
                if flow is None:
                    self._respond(400, b"oauth flow expired")
                    return
                try:
                    refresh_token, access_token = _exchange_authorization_code(
                        flow,
                        code,
                        outer._state.oauth_settings.google_oauth_client_secret,
                    )
                    outer._state.keyring.set_secret(
                        service=GOOGLE_KEYRING_SERVICE,
                        account=GOOGLE_REFRESH_TOKEN_ACCOUNT,
                        secret=refresh_token,
                    )
                except _OAuthExchangeError as error:
                    outer._state.last_oauth_error_code = error.safe_error_code
                    outer._state.last_oauth_error_description = error.safe_error_description
                    self._respond(
                        502,
                        f"Google OAuth token exchange failed: {error.safe_error_code}".encode(),
                    )
                    outer._finish_flow()
                    return
                outer._state.access_token = access_token
                outer._state.access_token_expires_at_ms = _now_ms() + DEFAULT_ACCESS_TOKEN_TTL_MS
                outer._state.connection_state = CredentialState.CONNECTED
                outer._state.last_checked_at_ms = _now_ms()
                outer._state.last_oauth_error_code = None
                outer._state.last_oauth_error_description = None
                self._respond(200, b"Google account connected. You can close this window.")
                outer._shutdown()

            def _respond(self, status: int, body: bytes) -> None:
                self.send_response(status)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, format: str, *args: object) -> None:  # noqa: A003
                del format, args

        return Handler

    def start(self) -> str:
        self._thread.start()
        return f"http://127.0.0.1:{self._server.server_port}/oauth/callback"

    def _finish_flow(self) -> None:
        self._state.active_flow = None
        self._shutdown()

    def _shutdown(self) -> None:
        threading.Thread(target=self._server.shutdown, daemon=True).start()


def _write(payload: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(payload, sort_keys=True) + "\n")
    sys.stdout.flush()


def _now_ms() -> int:
    return int(time.time() * 1000)


if __name__ == "__main__":
    main()
