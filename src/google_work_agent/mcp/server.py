"""Local MCP child process for Google OAuth credentials and read tools."""

from __future__ import annotations

import base64
import binascii
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
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from google_work_agent.adapters.keyring import OSKeyringSecretStore
from google_work_agent.adapters.mcp.transport import MANIFEST_MESSAGE_LIMIT_BYTES, PROTOCOL_VERSION
from google_work_agent.adapters.runtime.attachment_staging import (
    ATTACHMENT_STAGING_DIR_ENV,
    AttachmentDescriptor,
    AttachmentStagingError,
    LocalAttachmentStaging,
)
from google_work_agent.domain import build_p0_tool_registry, calculate_canonical_json_hash
from google_work_agent.mcp.settings import GoogleOAuthSettings
from google_work_agent.ports import CredentialState, OAuthEnvironment, SecretStore, TimeRange

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_KEYRING_SERVICE = "GoogleWorkAgent/DEVELOPMENT"
GOOGLE_REFRESH_TOKEN_ACCOUNT = "google-oauth-refresh-token"
REQUIRED_SCOPES = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
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

CLAIM_CONTEXT_VERSION = 2
CLAIM_CONTEXT_MAX_TTL_MS = 60_000
CLAIM_CONTEXT_REQUIRED_FIELDS = (
    "claim_version",
    "service_instance_id",
    "mcp_process_instance_id",
    "action_id",
    "approval_id",
    "execution_attempt_id",
    "tool_name",
    "approval_arguments_hash",
    "execution_arguments_hash",
    "issued_at_ms",
    "expires_at_ms",
    "nonce",
    "signature",
)
RECOVERY_MARKER_PREFIX = chr(0x200B) + "gwa-recovery-fingerprint:"

# The whole outer JSON-RPC line (id + payload + base64 attachment data) must
# fit inside MANIFEST_MESSAGE_LIMIT_BYTES on the stdio transport. Base64
# inflates raw bytes by ~4/3; this leaves headroom for JSON/envelope overhead.
MAX_ATTACHMENT_READ_BYTES = int(MANIFEST_MESSAGE_LIMIT_BYTES * 0.7 / 1.35)


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
    """A sanitized Google Workspace tool failure.

    ``dispatch_started`` records whether a real Google API request may have
    already been sent when this error was raised. It defaults to ``False``
    because most raise sites (argument validation, claim rejection, missing
    OAuth connection) run strictly before any Google call. Call sites that
    raise after invoking ``urlopen`` must pass ``dispatch_started=True`` so
    the client cannot mistake an ambiguous post-dispatch failure for a
    provably-not-sent one.
    """

    def __init__(self, safe_code: str, *, dispatch_started: bool = False) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code
        self.dispatch_started = dispatch_started


class _WorkspaceState:
    def __init__(self, *, keyring: SecretStore | None = None) -> None:
        self.process_instance_id = f"mcp-{secrets.token_hex(8)}"
        self.service_instance_id: str | None = None
        self.session_key: str | None = None
        # Consumed ClaimContextV2 nonces. The stdin dispatch loop in main()
        # processes one request at a time, so no lock is required: a claim
        # can only be validated and consumed by one in-flight request.
        self.used_nonces: set[str] = set()
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
            access_token, expires_at_ms, rotated_refresh_token, refreshed_email = (
                _refresh_access_token(
                    refresh_token,
                    self.oauth_settings.google_oauth_client_id,
                    self.oauth_settings.google_oauth_client_secret,
                )
            )
            self.access_token = access_token
            self.access_token_expires_at_ms = expires_at_ms
            if refreshed_email is not None:
                # Access tokens (and the id_token that arrives with them) are
                # process-memory-only, so a restarted MCP process re-derives
                # the account email here instead of requiring reconnect.
                self.account_email = refreshed_email
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
                        # Token refresh always runs before any workspace write dispatch.
                        "dispatch_started": False,
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
                        "dispatch_started": error.dispatch_started,
                    },
                }
            )
        except KeyError as error:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "NOT_FOUND",
                        "message": str(error),
                        "dispatch_started": True,
                    },
                }
            )
        except Exception:
            _write(
                {
                    "id": request_id,
                    "error": {
                        "code": "MALFORMED_RESPONSE",
                        "message": "MCP request failed.",
                        "dispatch_started": True,
                    },
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
    tools = {
        "gmail_search_threads": _gmail_search_threads,
        "gmail_get_ui_thread_detail": _gmail_get_ui_thread_detail,
        "gmail_get_thread": _gmail_get_thread,
        "gmail_get_message": _gmail_get_message,
        "gmail_get_draft": _gmail_get_draft,
        "gmail_get_attachment": _gmail_get_attachment,
        "gmail_create_draft": _gmail_create_draft,
        "gmail_update_draft": _gmail_update_draft,
        "gmail_send": _gmail_send,
        "tasks_list_tasklists": _tasks_list_tasklists,
        "tasks_list_tasks": _tasks_list_tasks,
        "tasks_get_task": _tasks_get_task,
        "tasks_create_task": _tasks_create_task,
        "tasks_update_task": _tasks_update_task,
        "tasks_delete_task": _tasks_delete_task,
        "calendar_list_calendars": _calendar_list_calendars,
        "calendar_list_events": _calendar_list_events,
        "calendar_get_event": _calendar_get_event,
        "calendar_query_freebusy": _calendar_query_freebusy,
        "calendar_create_event": _calendar_create_event,
        "calendar_update_event": _calendar_update_event,
        "calendar_delete_event": _calendar_delete_event,
        "search_by_recovery_fingerprint": _search_by_recovery_fingerprint,
    }
    handler = tools.get(tool_name)
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
        metadata = _gmail_thread_list_metadata(
            state=state,
            thread_id=thread_id,
            list_snippet=_optional_text(thread.get("snippet")),
        )
        items.append(
            _snapshot(
                "gmail_thread",
                thread_id,
                None,
                (),
                thread.get("historyId"),
                metadata,
            )
        )
    return {"items": items, "next_page_token": _optional_text(payload.get("nextPageToken"))}


def _gmail_thread_list_metadata(
    *,
    state: _WorkspaceState,
    thread_id: str,
    list_snippet: str | None,
) -> dict[str, object]:
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id, safe='')}",
        {"format": "metadata"},
    )
    messages = _object_list(payload.get("messages"))
    headers = _headers(messages[0]) if messages else {}
    sender_name, sender_email = _email_identity(headers.get("from"))
    return {
        "sender_name": sender_name,
        "sender_email": sender_email,
        "subject": _optional_text(headers.get("subject")),
        "received_at": _optional_text(headers.get("date"))
        or _first_message_internal_date(messages),
        "snippet": list_snippet or _optional_text(payload.get("snippet")),
    }


def _gmail_get_ui_thread_detail(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    thread_id = _text_argument(arguments, "thread_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id, safe='')}",
        {"format": "full"},
    )
    messages = _object_list(payload.get("messages"))
    if not messages:
        raise _WorkspaceToolError("NOT_FOUND")
    message = _latest_gmail_message(messages)
    message_id = _required_response_text(message, "id")
    headers = _headers(message)
    sender_name, sender_email = _email_identity(_decoded_header(headers.get("from")))
    recipients = _email_addresses(_decoded_header(headers.get("to")))
    cc = _email_addresses(_decoded_header(headers.get("cc")))
    return {
        "thread_id": thread_id,
        "message_id": message_id,
        "sender_name": sender_name,
        "sender_email": sender_email,
        "recipients": list(recipients),
        "cc": list(cc),
        "subject": _decoded_header(headers.get("subject")),
        "received_at": _optional_text(headers.get("date"))
        or _optional_text(message.get("internalDate")),
        "body": _gmail_message_body(message),
        "attachments": _gmail_attachment_metadata(message),
        "version": _optional_text(payload.get("historyId")) or "",
    }


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
    """Return one Gmail message snapshot including its actual body text.

    Agent Retrieval acquisition (unlike the Sidebar UI detail endpoint) reads
    this tool's payload directly into SourceSegment/Evidence text, so it must
    fetch ``format=full`` and extract the real body -- ``format=metadata``
    only returns headers and would leave Gmail evidence bodyless.
    """

    message_id = _text_argument(arguments, "message_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_id, safe='')}",
        {"format": "full"},
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
                "body": _gmail_message_body(payload),
                "attachments": _gmail_attachment_metadata(payload),
            },
        )
    }


def _gmail_get_draft(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    draft_id = _text_argument(arguments, "draft_id", maximum=2048)
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{quote(draft_id, safe='')}",
        {"format": "metadata"},
    )
    return {"item": _gmail_draft_snapshot(payload)}


def _gmail_get_attachment(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    """Return one Gmail attachment's bytes for the FastAPI download route to stream.

    This tool never touches Agent state, SQLite, or trace/audit output --
    the caller (a Local API route) streams the returned bytes straight to
    the browser and discards them. Attachments that would not fit inside a
    single stdio message are rejected rather than silently truncated.
    """

    message_id = _text_argument(arguments, "message_id", maximum=2048)
    attachment_id = _text_argument(arguments, "attachment_id", maximum=2048)
    payload = _google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages/"
        f"{quote(message_id, safe='')}/attachments/{quote(attachment_id, safe='')}",
    )
    raw_value = _optional_text(payload.get("data"))
    if raw_value is None:
        raise _WorkspaceToolError("INVALID_MCP_OUTPUT", dispatch_started=True)
    data = _b64url_decode(raw_value)
    if len(data) > MAX_ATTACHMENT_READ_BYTES:
        raise _WorkspaceToolError("ATTACHMENT_TOO_LARGE", dispatch_started=True)
    return {
        "message_id": message_id,
        "attachment_id": attachment_id,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "data_base64url": _b64url_encode(data),
    }


def _gmail_draft_snapshot(payload: dict[str, object]) -> dict[str, object]:
    draft_id = _required_response_text(payload, "id")
    message = cast(dict[str, object], payload.get("message") or {})
    headers = _headers(message)
    return _snapshot(
        "gmail_draft",
        draft_id,
        _optional_text(message.get("threadId")),
        (),
        message.get("historyId"),
        {
            "subject": headers.get("subject", draft_id),
            "to": headers.get("to"),
            "message_id": _optional_text(message.get("id")),
            "thread_id": _optional_text(message.get("threadId")),
        },
    )


def _gmail_create_draft(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="gmail_create_draft",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    mime_bytes = _build_gmail_mime(payload)
    body: dict[str, object] = {"message": {"raw": _b64url_encode(mime_bytes)}}
    thread_id = _optional_text(payload.get("thread_id"))
    if thread_id:
        cast(dict[str, object], body["message"])["threadId"] = thread_id
    response = _google_api_post(
        state, "https://gmail.googleapis.com/gmail/v1/users/me/drafts", body
    )
    return {"item": _gmail_draft_snapshot(response)}


def _gmail_update_draft(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    draft_id = _text_argument(arguments, "draft_id", maximum=2048)
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="gmail_update_draft",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    mime_bytes = _build_gmail_mime(payload)
    body: dict[str, object] = {"message": {"raw": _b64url_encode(mime_bytes)}}
    thread_id = _optional_text(payload.get("thread_id"))
    if thread_id:
        cast(dict[str, object], body["message"])["threadId"] = thread_id
    response = _google_api_call(
        state,
        "PUT",
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{quote(draft_id, safe='')}",
        body=body,
    )
    return {"item": _gmail_draft_snapshot(response)}


def _gmail_send(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    draft_id = _text_argument(arguments, "draft_id", maximum=2048)
    recovery_fingerprint = _optional_text(arguments.get("recovery_fingerprint"))
    _validate_claim_context(
        state,
        tool_name="gmail_send",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    if recovery_fingerprint:
        _embed_send_recovery_marker(
            state, draft_id=draft_id, recovery_fingerprint=recovery_fingerprint
        )
    response = _google_api_post(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts/send",
        {"id": draft_id},
    )
    headers = _headers(response)
    message_id = _required_response_text(response, "id")
    return {
        "item": _snapshot(
            "gmail_message",
            message_id,
            _optional_text(response.get("threadId")),
            (),
            response.get("historyId"),
            {
                "subject": headers.get("subject"),
                "sent": True,
                "draft_id": draft_id,
            },
        )
    }


def _embed_send_recovery_marker(
    state: _WorkspaceState, *, draft_id: str, recovery_fingerprint: str
) -> None:
    """Append a SEND-time recovery marker to the draft body before sending.

    A SEND's own recovery fingerprint differs from the CREATE draft's, and
    Gmail's send call cannot carry extra metadata, so the only way to make
    an uncertain SEND recoverable by content search is to fold the marker
    into the draft immediately before send -- an operational, server-generated
    edit ClaimContextV2's execution_arguments_hash already accounts for, not
    a change to any approved business content.
    """

    existing = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{quote(draft_id, safe='')}",
        {"format": "raw"},
    )
    raw_message = cast(dict[str, object], existing.get("message") or {})
    raw_value = _optional_text(raw_message.get("raw"))
    if raw_value is None:
        raise _WorkspaceToolError("INVALID_MCP_OUTPUT", dispatch_started=True)
    parsed = BytesParser(policy=policy.default).parsebytes(_b64url_decode(raw_value))
    body_text = ""
    if not parsed.is_multipart():
        content = parsed.get_content()
        if isinstance(content, str):
            body_text = content
    rebuilt = EmailMessage()
    for header in ("To", "Cc", "Bcc", "Subject"):
        value = parsed.get(header)
        if value is not None:
            rebuilt[header] = str(value)
    marker = _recovery_marker(recovery_fingerprint)
    rebuilt.set_content(f"{body_text}\n\n{marker}" if body_text else marker)
    _google_api_call(
        state,
        "PUT",
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{quote(draft_id, safe='')}",
        body={"message": {"raw": _b64url_encode(rebuilt.as_bytes())}},
    )


def _gmail_recipients(payload: dict[str, object], name: str, *, required: bool) -> list[str]:
    value = payload.get(name)
    if value is None:
        if required:
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        return []
    if not isinstance(value, list) or not value:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return [_text_value(item, maximum=320) for item in cast(list[object], value)]


def _build_gmail_mime(payload: dict[str, object]) -> bytes:
    to = _gmail_recipients(payload, "to", required=True)
    cc = _gmail_recipients(payload, "cc", required=False)
    bcc = _gmail_recipients(payload, "bcc", required=False)
    if len(to) + len(cc) + len(bcc) > 50:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    subject = _text_argument(payload, "subject", maximum=998, allow_empty=True)
    body = _text_argument(payload, "body", maximum=65536, allow_empty=True)
    message = EmailMessage()
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    if bcc:
        message["Bcc"] = ", ".join(bcc)
    message["Subject"] = subject
    # Only CREATE dispatch injects recovery_fingerprint into the payload
    # (see _build_final_dispatch_arguments); gmail_update_draft payloads
    # never carry it, so updates never gain or lose the marker.
    recovery_fingerprint = _optional_text(payload.get("recovery_fingerprint"))
    content = (
        f"{body}\n\n{_recovery_marker(recovery_fingerprint)}" if recovery_fingerprint else body
    )
    message.set_content(content)
    _attach_staged_files(message, payload)
    return message.as_bytes()


def _attachment_staging() -> LocalAttachmentStaging:
    staging_dir = os.environ.get(ATTACHMENT_STAGING_DIR_ENV)
    if not staging_dir:
        raise _WorkspaceToolError("ATTACHMENT_STAGING_UNAVAILABLE")
    return LocalAttachmentStaging(staging_dir=Path(staging_dir))


def _attach_staged_files(message: EmailMessage, payload: dict[str, object]) -> None:
    """Read and MIME-embed each staged attachment, re-verifying it first.

    Only descriptors (identity + hash) ever travel through Approval, Claim,
    and this argument payload; the actual bytes are read fresh from local
    staging immediately before assembly and are re-verified against the
    descriptor's recorded size/sha256 -- never trusted from the descriptor
    alone.
    """

    if "attachments" not in payload:
        return
    attachments = payload.get("attachments")
    if not isinstance(attachments, list) or len(attachments) > 10:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    staging = _attachment_staging()
    for item in cast(list[object], attachments):
        if not isinstance(item, dict):
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        try:
            descriptor = AttachmentDescriptor.from_json(cast(dict[str, object], item))
            data = staging.read_verified(descriptor)
        except AttachmentStagingError as error:
            raise _WorkspaceToolError(error.safe_code) from error
        maintype, _, subtype = descriptor.mime_type.partition("/")
        message.add_attachment(
            data,
            maintype=maintype or "application",
            subtype=subtype or "octet-stream",
            filename=descriptor.filename,
        )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii")


def _b64url_decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _recovery_marker(recovery_fingerprint: str) -> str:
    """Zero-width, body-embedded marker used to locate a write's own effect.

    Recovery search for CREATE/SEND has no server-assigned recovery ID to
    key off before the write happens, so the deterministic
    ``recovery_fingerprint`` computed at approval time is embedded into the
    resource's own searchable text (Gmail body, Task notes, Event
    description) and later located with a full-text/notes search. The
    leading zero-width space keeps it effectively invisible to the user
    without altering the approved visible content.
    """

    return f"{RECOVERY_MARKER_PREFIX}{recovery_fingerprint}"


def _dict_argument(arguments: dict[str, object], name: str) -> dict[str, object]:
    value = arguments.get(name)
    if not isinstance(value, dict):
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return cast(dict[str, object], value)


def _execution_arguments(arguments: dict[str, object]) -> dict[str, object]:
    """Return the tool arguments that ClaimContextV2 binds by hash.

    ``claim_context`` itself is excluded: it is the envelope carrying the
    hash, not part of the hashed payload.
    """

    return {key: value for key, value in arguments.items() if key != "claim_context"}


def _canonical_json_hash(value: object) -> str:
    return calculate_canonical_json_hash(value)


def _sign_claim_context(session_key: str, payload: dict[str, object]) -> str:
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(bytes.fromhex(session_key), normalized, hashlib.sha256).hexdigest()


def _validate_claim_context(
    state: _WorkspaceState,
    *,
    tool_name: str,
    claim_context: object,
    execution_arguments: dict[str, object],
) -> None:
    """Validate a signed ClaimContextV2 payload before any write dispatch.

    Every check below must pass before the nonce is consumed and before the
    caller performs any real Google mutation. On rejection the caller never
    reaches the Google API call, so ``dispatch_started`` stays ``False``.
    """

    if (
        state.session_key is None
        or state.service_instance_id is None
        or state.process_instance_id is None
    ):
        raise _WorkspaceToolError("CLAIM_SERVICE_UNAVAILABLE")
    if not isinstance(claim_context, dict):
        raise _WorkspaceToolError("CLAIM_MISSING")
    claim = cast(dict[str, object], claim_context)
    for field in CLAIM_CONTEXT_REQUIRED_FIELDS:
        if field not in claim:
            raise _WorkspaceToolError("CLAIM_MISSING")
    if claim.get("claim_version") != CLAIM_CONTEXT_VERSION:
        raise _WorkspaceToolError("CLAIM_VERSION_MISMATCH")
    signature = claim.get("signature")
    if not isinstance(signature, str) or not signature:
        raise _WorkspaceToolError("CLAIM_INVALID_SIGNATURE")
    unsigned = {key: value for key, value in claim.items() if key != "signature"}
    expected_signature = _sign_claim_context(state.session_key, unsigned)
    if not hmac.compare_digest(signature, expected_signature):
        raise _WorkspaceToolError("CLAIM_INVALID_SIGNATURE")
    for identity_field in ("action_id", "approval_id", "execution_attempt_id"):
        value = claim.get(identity_field)
        if not isinstance(value, str) or not value:
            raise _WorkspaceToolError("CLAIM_MALFORMED")
    if str(claim.get("tool_name")) != tool_name:
        raise _WorkspaceToolError("CLAIM_TOOL_MISMATCH")
    if str(claim.get("service_instance_id")) != state.service_instance_id:
        raise _WorkspaceToolError("CLAIM_SERVICE_INSTANCE_MISMATCH")
    if str(claim.get("mcp_process_instance_id")) != state.process_instance_id:
        raise _WorkspaceToolError("CLAIM_PROCESS_INSTANCE_MISMATCH")
    issued_at_ms = claim.get("issued_at_ms")
    expires_at_ms = claim.get("expires_at_ms")
    if not isinstance(issued_at_ms, int) or not isinstance(expires_at_ms, int):
        raise _WorkspaceToolError("CLAIM_MALFORMED")
    if expires_at_ms <= issued_at_ms or expires_at_ms - issued_at_ms > CLAIM_CONTEXT_MAX_TTL_MS:
        raise _WorkspaceToolError("CLAIM_TTL_EXCEEDED")
    if _now_ms() >= expires_at_ms:
        raise _WorkspaceToolError("CLAIM_EXPIRED")
    nonce = claim.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise _WorkspaceToolError("CLAIM_MALFORMED")
    if nonce in state.used_nonces:
        raise _WorkspaceToolError("CLAIM_TOKEN_REUSED")
    approval_hash = claim.get("approval_arguments_hash")
    if not isinstance(approval_hash, str) or not approval_hash:
        raise _WorkspaceToolError("CLAIM_MALFORMED")
    execution_hash = claim.get("execution_arguments_hash")
    if not isinstance(execution_hash, str) or not execution_hash:
        raise _WorkspaceToolError("CLAIM_MALFORMED")
    recomputed_hash = _canonical_json_hash(execution_arguments)
    if not hmac.compare_digest(recomputed_hash, execution_hash):
        raise _WorkspaceToolError("CLAIM_ARGUMENTS_MISMATCH")
    # Every check passed: consume the nonce now. main() dispatches one stdin
    # request at a time, so this is atomic with respect to concurrent claims.
    state.used_nonces.add(nonce)


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


def _tasks_create_task(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    task_list_id = _text_argument(arguments, "task_list_id", maximum=2048)
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="tasks_create_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    body = _task_write_body(payload, title_required=True)
    response = _google_api_post(
        state,
        f"https://tasks.googleapis.com/tasks/v1/lists/{quote(task_list_id, safe='')}/tasks",
        body,
    )
    return {"item": _task_snapshot(response, task_list_id)}


def _tasks_update_task(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    task_list_id = _text_argument(arguments, "task_list_id", maximum=2048)
    task_id = _text_argument(arguments, "task_id", maximum=2048)
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="tasks_update_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    body = _task_write_body(payload, title_required=False)
    if not body:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    task_list_path = quote(task_list_id, safe="")
    task_path = quote(task_id, safe="")
    response = _google_api_call(
        state,
        "PATCH",
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}",
        body=body,
    )
    return {"item": _task_snapshot(response, task_list_id)}


def _tasks_delete_task(state: _WorkspaceState, arguments: dict[str, object]) -> dict[str, object]:
    task_list_id = _text_argument(arguments, "task_list_id", maximum=2048)
    task_id = _text_argument(arguments, "task_id", maximum=2048)
    _validate_claim_context(
        state,
        tool_name="tasks_delete_task",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    task_list_path = quote(task_list_id, safe="")
    task_path = quote(task_id, safe="")
    _google_api_call(
        state,
        "DELETE",
        f"https://tasks.googleapis.com/tasks/v1/lists/{task_list_path}/tasks/{task_path}",
    )
    return {
        "item": _snapshot(
            "task",
            task_id,
            task_list_id,
            (task_list_id,),
            "deleted",
            {"status": "deleted"},
        )
    }


def _task_write_body(payload: dict[str, object], *, title_required: bool) -> dict[str, object]:
    body: dict[str, object] = {}
    if "title" in payload or title_required:
        body["title"] = _text_argument(payload, "title", maximum=1024)
    # Only CREATE dispatch injects recovery_fingerprint into the payload
    # (see _build_final_dispatch_arguments); tasks_update_task never carries it.
    recovery_fingerprint = _optional_text(payload.get("recovery_fingerprint"))
    if "notes" in payload or recovery_fingerprint:
        notes = _optional_text(payload.get("notes"))
        if recovery_fingerprint:
            marker = _recovery_marker(recovery_fingerprint)
            notes = f"{notes}\n\n{marker}" if notes else marker
        if notes:
            body["notes"] = notes
    if "due" in payload:
        due = _optional_text(payload.get("due"))
        if due:
            body["due"] = due
    if "status" in payload:
        status = _optional_text(payload.get("status"))
        if status not in {"needsAction", "completed"}:
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        body["status"] = status
    return body


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
    params = _page_params(arguments)
    time_min = arguments.get("time_min")
    if time_min is not None:
        params["timeMin"] = _text_value(time_min, maximum=64)
    time_max = arguments.get("time_max")
    if time_max is not None:
        params["timeMax"] = _text_value(time_max, maximum=64)
    single_events = arguments.get("single_events")
    if single_events is not None:
        if not isinstance(single_events, bool):
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        params["singleEvents"] = "true" if single_events else "false"
    order_by = arguments.get("order_by")
    if order_by is not None:
        order_by_value = _text_value(order_by, maximum=32)
        if order_by_value != "startTime" or single_events is not True:
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        params["orderBy"] = order_by_value
    payload = _google_api(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
        params,
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


def _calendar_create_event(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = _text_argument(arguments, "calendar_id", maximum=2048)
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="calendar_create_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    body: dict[str, object] = {
        "summary": _text_argument(payload, "title", maximum=1024),
        "start": {"dateTime": _text_argument(payload, "start", maximum=64)},
        "end": {"dateTime": _text_argument(payload, "end", maximum=64)},
    }
    description = _optional_text(payload.get("description"))
    # Only CREATE dispatch injects recovery_fingerprint into the payload
    # (see _build_final_dispatch_arguments); calendar_update_event never
    # carries it.
    recovery_fingerprint = _optional_text(payload.get("recovery_fingerprint"))
    if recovery_fingerprint:
        marker = _recovery_marker(recovery_fingerprint)
        description = f"{description}\n\n{marker}" if description else marker
    if description:
        body["description"] = description
    attendees = _calendar_attendees_argument(payload)
    if attendees is not None:
        body["attendees"] = attendees
    response = _google_api_post(
        state,
        f"https://www.googleapis.com/calendar/v3/calendars/{quote(calendar_id, safe='')}/events",
        body,
    )
    return {"item": _event_snapshot(response, calendar_id)}


def _calendar_update_event(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = _text_argument(arguments, "calendar_id", maximum=2048)
    event_id = _text_argument(arguments, "event_id", maximum=2048)
    payload = _dict_argument(arguments, "payload")
    _validate_claim_context(
        state,
        tool_name="calendar_update_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    body: dict[str, object] = {}
    if "title" in payload:
        body["summary"] = _text_argument(payload, "title", maximum=1024, allow_empty=True)
    if "start" in payload:
        body["start"] = {"dateTime": _text_argument(payload, "start", maximum=64)}
    if "end" in payload:
        body["end"] = {"dateTime": _text_argument(payload, "end", maximum=64)}
    if "description" in payload:
        description = _optional_text(payload.get("description"))
        if description:
            body["description"] = description
    attendees = _calendar_attendees_argument(payload)
    if attendees is not None:
        body["attendees"] = attendees
    if not body:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    calendar_path = quote(calendar_id, safe="")
    event_path = quote(event_id, safe="")
    response = _google_api_call(
        state,
        "PATCH",
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
        body=body,
    )
    return {"item": _event_snapshot(response, calendar_id)}


def _calendar_delete_event(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    calendar_id = _text_argument(arguments, "calendar_id", maximum=2048)
    event_id = _text_argument(arguments, "event_id", maximum=2048)
    _validate_claim_context(
        state,
        tool_name="calendar_delete_event",
        claim_context=arguments.get("claim_context"),
        execution_arguments=_execution_arguments(arguments),
    )
    calendar_path = quote(calendar_id, safe="")
    event_path = quote(event_id, safe="")
    _google_api_call(
        state,
        "DELETE",
        f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events/{event_path}",
    )
    return {
        "item": _snapshot(
            "calendar_event",
            event_id,
            calendar_id,
            (calendar_id,),
            "deleted",
            {"status": "cancelled"},
        )
    }


def _calendar_attendees_argument(payload: dict[str, object]) -> list[dict[str, object]] | None:
    if "attendees" not in payload:
        return None
    value = payload.get("attendees")
    if not isinstance(value, list):
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return [{"email": _text_value(item, maximum=320)} for item in cast(list[object], value)]


def _search_by_recovery_fingerprint(
    state: _WorkspaceState, arguments: dict[str, object]
) -> dict[str, object]:
    """Locate resources by their embedded recovery marker.

    This is a READ-only lookup used exclusively by UNKNOWN_RESULT recovery
    (never by ordinary write dispatch), so it carries no claim_context: it
    cannot mutate anything, and the caller's own domain/application layer
    is responsible for treating anything other than exactly one match as
    unresolved (see RecoverUnknownCreateActionService).
    """

    resource_type = _text_argument(arguments, "resource_type", maximum=64)
    fingerprint = _text_argument(arguments, "recovery_fingerprint", maximum=512)
    marker = _recovery_marker(fingerprint)
    if resource_type == "gmail_draft":
        items = _search_gmail_drafts_by_marker(state, marker)
    elif resource_type == "gmail_message":
        items = _search_gmail_messages_by_marker(state, marker)
    elif resource_type == "task":
        items = _search_tasks_by_marker(state, marker)
    elif resource_type == "calendar_event":
        items = _search_calendar_events_by_marker(state, marker)
    else:
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return {"items": items}


def _search_gmail_drafts_by_marker(state: _WorkspaceState, marker: str) -> list[dict[str, object]]:
    payload = _google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/drafts",
        {"q": marker, "maxResults": "10"},
    )
    draft_ids = [
        _required_response_text(item, "id") for item in _object_list(payload.get("drafts"))
    ]
    if len(draft_ids) != 1:
        # Zero or multiple candidates: the caller only accepts an exact
        # single match, so minimal identity-only snapshots are enough.
        return [_snapshot("gmail_draft", draft_id, None, (), None, {}) for draft_id in draft_ids]
    detail = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/drafts/{quote(draft_ids[0], safe='')}",
        {"format": "metadata"},
    )
    return [_gmail_draft_snapshot(detail)]


def _search_gmail_messages_by_marker(
    state: _WorkspaceState, marker: str
) -> list[dict[str, object]]:
    payload = _google_api(
        state,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        {"q": marker, "maxResults": "10"},
    )
    message_ids = [
        _required_response_text(item, "id") for item in _object_list(payload.get("messages"))
    ]
    if len(message_ids) != 1:
        return [
            _snapshot("gmail_message", message_id, None, (), None, {}) for message_id in message_ids
        ]
    detail = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{quote(message_ids[0], safe='')}",
        {"format": "metadata"},
    )
    headers = _headers(detail)
    return [
        _snapshot(
            "gmail_message",
            message_ids[0],
            _optional_text(detail.get("threadId")),
            (),
            detail.get("historyId"),
            {"subject": headers.get("subject", message_ids[0]), "sent": True},
        )
    ]


def _search_tasks_by_marker(state: _WorkspaceState, marker: str) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    task_lists_payload = _google_api(
        state, "https://tasks.googleapis.com/tasks/v1/users/@me/lists", {"maxResults": "100"}
    )
    for task_list in _object_list(task_lists_payload.get("items")):
        task_list_id = _required_response_text(task_list, "id")
        tasks_payload = _google_api(
            state,
            f"https://tasks.googleapis.com/tasks/v1/lists/{quote(task_list_id, safe='')}/tasks",
            {"maxResults": "100", "showHidden": "true"},
        )
        for item in _object_list(tasks_payload.get("items")):
            notes = _optional_text(item.get("notes"))
            if notes and marker in notes:
                matches.append(_task_snapshot(item, task_list_id))
    return matches


def _search_calendar_events_by_marker(
    state: _WorkspaceState, marker: str
) -> list[dict[str, object]]:
    matches: list[dict[str, object]] = []
    calendars_payload = _google_api(
        state,
        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
        {"maxResults": "100"},
    )
    for calendar in _object_list(calendars_payload.get("items")):
        calendar_id = _required_response_text(calendar, "id")
        calendar_path = quote(calendar_id, safe="")
        events_payload = _google_api(
            state,
            f"https://www.googleapis.com/calendar/v3/calendars/{calendar_path}/events",
            {"q": marker, "maxResults": "10"},
        )
        for item in _object_list(events_payload.get("items")):
            matches.append(_event_snapshot(item, calendar_id))
    return matches


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
    self_response_status = next(
        (
            _optional_text(attendee.get("responseStatus"))
            for attendee in _object_list(item.get("attendees"))
            if attendee.get("self") is True
        ),
        None,
    )
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
            "self_response_status": self_response_status,
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


def _google_api_call(
    state: _WorkspaceState,
    method: str,
    url: str,
    *,
    params: dict[str, str] | None = None,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        state.ensure_access_token()
    except _OAuthReauthenticationRequired as error:
        state.connection_state = CredentialState.REAUTH_REQUIRED
        raise _WorkspaceToolError("REAUTH_REQUIRED") from error
    if state.access_token is None:
        raise _WorkspaceToolError("OAUTH_NOT_CONNECTED")
    request_url = f"{url}?{urlencode(params)}" if params else url
    headers = {"Authorization": f"Bearer {state.access_token}", "Accept": "application/json"}
    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(request_url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=GOOGLE_API_TIMEOUT_SECONDS) as response:  # nosec B310: fixed Google API endpoints
            raw = response.read()
            if not raw:
                return {}
            return cast(dict[str, object], json.loads(raw.decode("utf-8")))
    except HTTPError as error:
        codes = {
            401: "REAUTH_REQUIRED",
            403: "PERMISSION_DENIED",
            404: "NOT_FOUND",
            409: "CONFLICT",
            412: "CONFLICT",
            429: "RATE_LIMITED",
        }
        if error.code == 401:
            state.connection_state = CredentialState.REAUTH_REQUIRED
            state.access_token = None
            state.access_token_expires_at_ms = 0
        # A response (even an error one) proves the request reached Google.
        raise _WorkspaceToolError(
            codes.get(error.code, "UPSTREAM_5XX" if error.code >= 500 else "GOOGLE_REQUEST_FAILED"),
            dispatch_started=True,
        ) from error
    except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise _WorkspaceToolError(
            "TIMEOUT" if isinstance(error, TimeoutError) else "MCP_UNAVAILABLE",
            dispatch_started=True,
        ) from error


def _google_api(
    state: _WorkspaceState, url: str, params: dict[str, str] | None = None
) -> dict[str, object]:
    return _google_api_call(state, "GET", url, params=params)


def _google_api_post(
    state: _WorkspaceState, url: str, body: dict[str, object]
) -> dict[str, object]:
    return _google_api_call(state, "POST", url, body=body)


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


def _latest_gmail_message(messages: list[dict[str, object]]) -> dict[str, object]:
    def sort_key(indexed: tuple[int, dict[str, object]]) -> tuple[int, int]:
        index, message = indexed
        internal_date = _optional_text(message.get("internalDate"))
        return (int(internal_date) if internal_date and internal_date.isdigit() else -1, index)

    return max(enumerate(messages), key=sort_key)[1]


def _decoded_header(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        return _optional_text(str(make_header(decode_header(value))))
    except (LookupError, UnicodeError):
        return _optional_text(value)


def _email_addresses(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    addresses = []
    for name, email in getaddresses([value]):
        normalized_email = _optional_text(email)
        if normalized_email is None:
            continue
        normalized_name = _optional_text(name)
        addresses.append(
            f"{normalized_name} <{normalized_email}>" if normalized_name else normalized_email
        )
    return tuple(addresses)


def _gmail_message_body(message: dict[str, object]) -> str | None:
    payload = cast(dict[str, object], message.get("payload") or {})
    plain_parts: list[str] = []
    html_parts: list[str] = []
    _collect_gmail_body_parts(payload, plain_parts=plain_parts, html_parts=html_parts)
    if plain_parts:
        return _optional_text("\n\n".join(plain_parts))
    if html_parts:
        parser = _ReadableHtmlParser()
        parser.feed("\n".join(html_parts))
        parser.close()
        return parser.readable_text()
    return None


def _collect_gmail_body_parts(
    part: dict[str, object], *, plain_parts: list[str], html_parts: list[str]
) -> None:
    mime_type = (_optional_text(part.get("mimeType")) or "").lower()
    filename = _optional_text(part.get("filename"))
    body = cast(dict[str, object], part.get("body") or {})
    data = _optional_text(body.get("data"))
    if filename is None and data is not None and mime_type in {"text/plain", "text/html"}:
        decoded = _decode_gmail_text(data, charset=_gmail_part_charset(part))
        if decoded:
            (plain_parts if mime_type == "text/plain" else html_parts).append(decoded)
    for child in _object_list(part.get("parts")):
        _collect_gmail_body_parts(child, plain_parts=plain_parts, html_parts=html_parts)


def _decode_gmail_text(data: str, *, charset: str | None) -> str | None:
    try:
        raw = _b64url_decode(data)
    except (ValueError, binascii.Error):
        return None
    try:
        return _optional_text(raw.decode(charset or "utf-8", errors="replace"))
    except LookupError:
        return _optional_text(raw.decode("utf-8", errors="replace"))


def _gmail_part_charset(part: dict[str, object]) -> str | None:
    headers = {
        str(item.get("name", "")).lower(): str(item.get("value", ""))
        for item in _object_list(part.get("headers"))
        if item.get("name") and item.get("value")
    }
    content_type = headers.get("content-type", "")
    match = re.search(r"charset\s*=\s*[\"']?([^;\"'\s]+)", content_type, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _gmail_attachment_metadata(message: dict[str, object]) -> list[dict[str, object]]:
    message_id = _required_response_text(message, "id")
    payload = cast(dict[str, object], message.get("payload") or {})
    results: list[dict[str, object]] = []

    def visit(part: dict[str, object]) -> None:
        body = cast(dict[str, object], part.get("body") or {})
        filename = _decoded_header(_optional_text(part.get("filename")))
        attachment_id = _optional_text(body.get("attachmentId"))
        if filename is not None and attachment_id is not None:
            size = body.get("size")
            results.append(
                {
                    "message_id": message_id,
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": _optional_text(part.get("mimeType")) or "application/octet-stream",
                    "size_bytes": size if isinstance(size, int) and size >= 0 else None,
                }
            )
        for child in _object_list(part.get("parts")):
            visit(child)

    visit(payload)
    return results


class _ReadableHtmlParser(HTMLParser):
    _BLOCK_TAGS = {"br", "div", "p", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._ignored_depth:
            self._ignored_depth -= 1
        elif not self._ignored_depth and tag in self._BLOCK_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._chunks.append(data)

    def readable_text(self) -> str | None:
        lines = [" ".join(line.split()) for line in "".join(self._chunks).splitlines()]
        return _optional_text("\n".join(line for line in lines if line))


def _email_identity(value: str | None) -> tuple[str | None, str | None]:
    if value is None:
        return None, None
    name, email = parseaddr(value)
    return _optional_text(name), _optional_text(email)


def _first_message_internal_date(messages: list[dict[str, object]]) -> str | None:
    if not messages:
        return None
    return _optional_text(messages[0].get("internalDate"))


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
) -> tuple[str, str | None, str | None]:
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
    id_token = payload.get("id_token")
    email = _verified_email_from_id_token(id_token) if isinstance(id_token, str) else None
    return (
        refresh_token,
        access_token if isinstance(access_token, str) else None,
        email,
    )


def _verified_email_from_id_token(id_token: str) -> str | None:
    """Extract the account email from Google's ID token, if present.

    The token was just fetched directly from Google's token endpoint over
    TLS (not presented by an untrusted client), so this only decodes the
    payload segment rather than verifying its signature -- there is no
    front-channel replay/injection risk to guard against here. Only an
    explicitly verified email claim is used, matching Google's own
    ``email_verified`` semantics.
    """

    try:
        _header, payload_segment, _signature = id_token.split(".", 2)
        claims = cast(dict[str, object], json.loads(_b64url_decode(payload_segment)))
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError, binascii.Error):
        return None
    if claims.get("email_verified") is not True:
        return None
    email = claims.get("email")
    return email if isinstance(email, str) and email.strip() else None


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
) -> tuple[str, int, str | None, str | None]:
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
    id_token = payload.get("id_token")
    email = _verified_email_from_id_token(id_token) if isinstance(id_token, str) else None
    return (
        access_token,
        _now_ms() + ttl_ms,
        rotated if isinstance(rotated, str) else None,
        email,
    )


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
                    refresh_token, access_token, email = _exchange_authorization_code(
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
                outer._state.account_email = email
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
