"""Private Google Workspace MCP provider mechanics used by the canonical server."""

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
from collections.abc import Mapping
from dataclasses import dataclass, field
from email import policy
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import getaddresses, parseaddr
from enum import StrEnum
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urlencode, urlparse
from urllib.request import Request, urlopen

from google_work_agent.adapters.connectors.runtime.stdio_mcp_client import (
    MANIFEST_MESSAGE_LIMIT_BYTES,
)
from google_work_agent.adapters.keyring.os_keyring_secret_store import (
    OsKeyringSecretStoreAdapter,
    keyring_service_name,
)
from google_work_agent.adapters.system.filesystem_attachment_staging import (
    ATTACHMENT_STAGING_DIR_ENV,
    AttachmentStagingError,
    FilesystemAttachmentStagingAdapter,
    StagedAttachmentDescriptorV1,
)
from google_work_agent.ports.connector.oauth_credential_port import OAuthEnvironment
from google_work_agent.ports.keyring.secret_store_port import SecretStorePort

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEVELOPMENT_ENVIRONMENT = "DEVELOPMENT"


@dataclass(frozen=True, slots=True)
class GoogleOAuthSettings:
    """Desktop OAuth configuration; only the public client ID is configurable."""

    google_oauth_client_id: str | None = field(repr=False)

    @classmethod
    def load(
        cls,
        *,
        runtime_environment: str,
        environment: dict[str, str] | None = None,
    ) -> GoogleOAuthSettings:
        values = (
            _load_env_file(PROJECT_ROOT / ".env.local")
            if runtime_environment.upper() == DEVELOPMENT_ENVIRONMENT
            else {}
        )
        values.update(dict(os.environ) if environment is None else environment)
        client_id = values.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        return cls(google_oauth_client_id=client_id or None)


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            values[key] = value.strip().strip("\"'")
    return values


class CredentialState(StrEnum):
    NOT_CONNECTED = "NOT_CONNECTED"
    CONNECTED = "CONNECTED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    KEYRING_UNAVAILABLE = "KEYRING_UNAVAILABLE"
    ERROR = "ERROR"


GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://openidconnect.googleapis.com/v1/userinfo"
GOOGLE_REVOKE_ENDPOINT = "https://oauth2.googleapis.com/revoke"
GOOGLE_REFRESH_TOKEN_ACCOUNT = "google_workspace"
GOOGLE_REFRESH_TOKEN_KEY = GOOGLE_REFRESH_TOKEN_ACCOUNT
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
GMAIL_METADATA_HYDRATION_MAX_WORKERS = 3

CLAIM_CONTEXT_VERSION = 2
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
    operation_ref: str


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


@dataclass(frozen=True, slots=True)
class _UserInfoIdentityResolution:
    email: str | None
    http_status: int | None


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


class GoogleWorkspaceCredentialProvider:
    def __init__(self, *, keyring: SecretStorePort | None = None) -> None:
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
        self.operational_results: dict[str, dict[str, object]] = {}
        raw_environment = os.environ.get("GOOGLE_OAUTH_ENV", "")
        if not raw_environment and keyring is not None:
            raw_environment = OAuthEnvironment.DEVELOPMENT.value
        try:
            self.oauth_environment = OAuthEnvironment(
                raw_environment.upper()
            )
        except ValueError as error:
            raise RuntimeError("GOOGLE_OAUTH_ENV_INVALID") from error
        self.oauth_settings = GoogleOAuthSettings.load(
            runtime_environment=self.oauth_environment.value,
        )
        self.keyring = keyring or OsKeyringSecretStoreAdapter(
            service_name=keyring_service_name(
                environment=self.oauth_environment.value,
                credential_type="google-oauth",
            )
        )
        if self.keyring.get(GOOGLE_REFRESH_TOKEN_KEY) is not None:
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
            "oauth_environment": self.oauth_environment.value,
            "last_checked_at_ms": self.last_checked_at_ms,
            "safe_error_code": self.last_oauth_error_code,
            "safe_error_description": self.last_oauth_error_description,
        }

    def ensure_access_token(self) -> None:
        if (
            self.access_token is not None
            and _now_ms() < self.access_token_expires_at_ms
            and self.account_email is not None
        ):
            return
        with self._refresh_lock:
            if self.access_token is not None and _now_ms() < self.access_token_expires_at_ms:
                if self.account_email is None:
                    resolution = _resolve_account_identity_from_userinfo(self.access_token)
                    self.account_email = (
                        self._recover_identity_after_userinfo_401()
                        if resolution.http_status == 401
                        else resolution.email
                    )
                return
            refresh_bytes = self.keyring.get(GOOGLE_REFRESH_TOKEN_KEY)
            refresh_token = None if refresh_bytes is None else refresh_bytes.decode("utf-8")
            if refresh_token is None:
                self.connection_state = CredentialState.NOT_CONNECTED
                return
            access_token, expires_at_ms, rotated_refresh_token, refreshed_email = (
                _refresh_access_token(
                    refresh_token,
                    self.oauth_settings.google_oauth_client_id,
                )
            )
            self.access_token = access_token
            self.access_token_expires_at_ms = expires_at_ms
            if refreshed_email is not None:
                # Access tokens (and the id_token that arrives with them) are
                # process-memory-only, so a restarted MCP process re-derives
                # the account email here instead of requiring reconnect.
                self.account_email = refreshed_email
            elif self.account_email is None:
                # A refresh response commonly omits id_token. The originally
                # granted openid/userinfo.email scope still permits resolving
                # the verified identity from this newly refreshed access token.
                # Failure here must not downgrade an otherwise usable OAuth
                # credential used by the Workspace read tools.
                self.account_email = _resolve_account_identity_from_userinfo(access_token).email
            if rotated_refresh_token is not None:
                self.keyring.put(GOOGLE_REFRESH_TOKEN_KEY, rotated_refresh_token.encode("utf-8"))
            self.connection_state = CredentialState.CONNECTED

    def _recover_identity_after_userinfo_401(self) -> str | None:
        refresh_bytes = self.keyring.get(GOOGLE_REFRESH_TOKEN_KEY)
        refresh_token = None if refresh_bytes is None else refresh_bytes.decode("utf-8")
        if refresh_token is None:
            raise _OAuthReauthenticationRequired
        try:
            access_token, expires_at_ms, rotated_refresh_token, refreshed_email = (
                _refresh_access_token(
                    refresh_token,
                    self.oauth_settings.google_oauth_client_id,
                )
            )
        except _OAuthReauthenticationRequired:
            raise
        except _OAuthExchangeError as error:
            raise _OAuthReauthenticationRequired from error
        self.access_token = access_token
        self.access_token_expires_at_ms = expires_at_ms
        if rotated_refresh_token is not None:
            self.keyring.put(GOOGLE_REFRESH_TOKEN_KEY, rotated_refresh_token.encode("utf-8"))
        self.connection_state = CredentialState.CONNECTED
        if refreshed_email is not None:
            return refreshed_email
        retry = _resolve_account_identity_from_userinfo(access_token)
        if retry.http_status == 401:
            self.connection_state = CredentialState.REAUTH_REQUIRED
            self.access_token = None
            self.access_token_expires_at_ms = 0
        return retry.email


def _gmail_thread_list_metadata(
    *,
    state: GoogleWorkspaceCredentialProvider,
    thread_id: str,
    list_snippet: str | None,
) -> dict[str, object]:
    payload = _google_api(
        state,
        f"https://gmail.googleapis.com/gmail/v1/users/me/threads/{quote(thread_id, safe='')}",
        {
            "format": "metadata",
            "metadataHeaders": ["From", "Subject", "Date"],
            "fields": "messages(internalDate,payload/headers),snippet",
        },
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


def _embed_send_recovery_marker(
    state: GoogleWorkspaceCredentialProvider, *, draft_id: str, recovery_fingerprint: str
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


def _attachment_staging() -> FilesystemAttachmentStagingAdapter:
    staging_dir = os.environ.get(ATTACHMENT_STAGING_DIR_ENV)
    if not staging_dir:
        raise _WorkspaceToolError("ATTACHMENT_STAGING_UNAVAILABLE")
    return FilesystemAttachmentStagingAdapter(staging_dir=Path(staging_dir))


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
            descriptor = StagedAttachmentDescriptorV1.from_json(cast(dict[str, object], item))
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


def _validate_claim_context(
    state: GoogleWorkspaceCredentialProvider,
    *,
    tool_name: str,
    claim_context: object,
    execution_arguments: dict[str, object],
) -> None:
    from .validate_claim_context import (
        validate_claim_context,
    )

    validate_claim_context(
        state,
        tool_name=tool_name,
        claim_context=claim_context,
        execution_arguments=execution_arguments,
    )


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
    if "scheduled_date" in payload:
        scheduled_date = _optional_text(payload.get("scheduled_date"))
        if scheduled_date:
            body["due"] = scheduled_date
        elif not title_required:
            # An approved update may intentionally remove a prior scheduled date.
            body["due"] = None
    elif "due" in payload:
        # Legacy raw Provider-boundary payloads remain compatible.
        due = _optional_text(payload.get("due"))
        if due:
            body["due"] = due
    if "status" in payload:
        status = _optional_text(payload.get("status"))
        if status not in {"needsAction", "completed"}:
            raise _WorkspaceToolError("INVALID_ARGUMENT")
        body["status"] = status
    return body


def _calendar_attendees_argument(payload: dict[str, object]) -> list[dict[str, object]] | None:
    if "attendees" not in payload:
        return None
    value = payload.get("attendees")
    if not isinstance(value, list):
        raise _WorkspaceToolError("INVALID_ARGUMENT")
    return [{"email": _text_value(item, maximum=320)} for item in cast(list[object], value)]


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
            "completed": _optional_text(item.get("completed")),
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
    attendees = [
        email
        for attendee in _object_list(item.get("attendees"))
        if (email := _optional_text(attendee.get("email"))) is not None
    ]
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
            "timezone": _optional_text(start.get("timeZone"))
            or _optional_text(end.get("timeZone"))
            or "UTC",
            "attendees": attendees,
            "location": _optional_text(item.get("location")),
            "description": _optional_text(item.get("description")),
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
    state: GoogleWorkspaceCredentialProvider,
    method: str,
    url: str,
    *,
    params: Mapping[str, str | list[str]] | None = None,
    body: dict[str, object] | None = None,
) -> dict[str, object]:
    try:
        state.ensure_access_token()
    except _OAuthReauthenticationRequired as error:
        state.connection_state = CredentialState.REAUTH_REQUIRED
        raise _WorkspaceToolError("REAUTH_REQUIRED") from error
    if state.access_token is None:
        raise _WorkspaceToolError("OAUTH_NOT_CONNECTED")
    request_url = f"{url}?{urlencode(params, doseq=True)}" if params else url
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
    state: GoogleWorkspaceCredentialProvider,
    url: str,
    params: Mapping[str, str | list[str]] | None = None,
) -> dict[str, object]:
    return _google_api_call(state, "GET", url, params=params)


def _google_api_post(
    state: GoogleWorkspaceCredentialProvider, url: str, body: dict[str, object]
) -> dict[str, object]:
    return _google_api_call(state, "POST", url, body=body)


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


def _control_call(
    state: GoogleWorkspaceCredentialProvider,
    *,
    method: str,
    arguments: dict[str, object] | None = None,
) -> dict[str, object]:
    arguments = arguments or {}
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
        operation_ref = str(arguments.get("operation_ref", ""))
        refresh_bytes = state.keyring.get(GOOGLE_REFRESH_TOKEN_KEY)
        refresh_token = None if refresh_bytes is None else refresh_bytes.decode("utf-8")
        revoke_succeeded = (
            _revoke_refresh_token(refresh_token) if refresh_token is not None else False
        )
        deleted = refresh_token is not None
        state.keyring.delete(GOOGLE_REFRESH_TOKEN_KEY)
        state.connection_state = CredentialState.NOT_CONNECTED
        state.access_token = None
        state.access_token_expires_at_ms = 0
        state.account_email = None
        state.display_name = None
        state.last_checked_at_ms = _now_ms()
        result: dict[str, object] = {
            "disconnected": True,
            "credential_deleted": deleted,
            "revoke_attempted": refresh_token is not None,
            "revoke_succeeded": revoke_succeeded,
            "credential_state": state.connection_state.value,
        }
        if operation_ref:
            state.operational_results[operation_ref] = result
        return result
    if method == "google.connection.refresh":
        state.ensure_access_token()
        if state.access_token is None:
            raise _WorkspaceToolError("REAUTH_REQUIRED")
        account_id = str(arguments.get("account_id", ""))
        handle = hmac.new(
            bytes.fromhex(state.session_key or "00" * 32),
            f"{state.process_instance_id}:{account_id}".encode(),
            hashlib.sha256,
        ).hexdigest()
        return {"access_context_handle": handle}
    if method in {
        "google.oauth.reconcile_start",
        "google.connection.reconcile_disconnect",
    }:
        operation_ref = str(arguments.get("operation_ref", ""))
        stored = state.operational_results.get(operation_ref)
        if stored is None:
            return {"status": "SAFE_TO_RETRY", "result_ref": None, "bounded_result": None}
        return {
            "status": "COMPLETED",
            "result_ref": operation_ref,
            "bounded_result": stored,
        }
    if method == "google.oauth.start":
        if state.oauth_settings.google_oauth_client_id is None:
            raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
        if state.active_flow is not None and state.active_flow.expires_at_ms > _now_ms():
            raise ValueError("oauth flow already active")
        operation_ref = str(arguments.get("operation_ref", ""))
        if not operation_ref:
            raise ValueError("operation_ref is required")
        flow = _start_oauth_flow(state, operation_ref=operation_ref)
        state.last_oauth_error_code = None
        state.last_oauth_error_description = None
        state.active_flow = flow
        result = cast(
            dict[str, object],
            {
                "flow_id": flow.flow_id,
                "authorization_url": _authorization_url(flow),
                "callback_url": flow.callback_url,
                "expires_at_ms": flow.expires_at_ms,
                "oauth_environment": state.oauth_environment.value,
                "scopes": list(REQUIRED_SCOPES),
            },
        )
        state.operational_results[operation_ref] = {
            "callback_id": flow.flow_id,
            "authorization_url": result["authorization_url"],
        }
        return result
    raise ValueError("unsupported control method")


def _start_oauth_flow(
    state: GoogleWorkspaceCredentialProvider, *, operation_ref: str
) -> _OAuthFlow:
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
        operation_ref=operation_ref,
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
) -> tuple[str, str | None, str | None]:
    body = urlencode(
        {
            "client_id": flow.client_id,
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


def _resolve_account_identity_from_userinfo(access_token: str) -> _UserInfoIdentityResolution:
    request = Request(
        GOOGLE_USERINFO_ENDPOINT,
        headers={"Authorization": f"Bearer {access_token}"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=10) as response:  # nosec B310: fixed Google endpoint
            payload = cast(dict[str, object], json.loads(response.read().decode("utf-8")))
    except HTTPError as error:
        return _UserInfoIdentityResolution(email=None, http_status=error.code)
    except TimeoutError:
        return _UserInfoIdentityResolution(email=None, http_status=None)
    except URLError:
        return _UserInfoIdentityResolution(email=None, http_status=None)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _UserInfoIdentityResolution(email=None, http_status=None)
    email = _verified_email_from_userinfo_payload(payload)
    return _UserInfoIdentityResolution(
        email=email,
        http_status=getattr(response, "status", 200),
    )


def _verified_email_from_userinfo_payload(payload: dict[str, object]) -> str | None:
    """Accept only a complete, verified OIDC identity response."""

    sub = payload.get("sub")
    email = payload.get("email")
    if (
        not isinstance(sub, str)
        or not sub.strip()
        or payload.get("email_verified") is not True
        or not isinstance(email, str)
        or not email.strip()
    ):
        return None
    return email


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
        r"(?i)\b(code|token|verifier|state|client_secret|secret)=([^\s&,]+)",
        r"\1=[REDACTED]",
        redacted,
    )
    normalized = " ".join(redacted.split())
    return normalized[:240] or None


def _refresh_access_token(
    refresh_token: str,
    client_id: str | None,
) -> tuple[str, int, str | None, str | None]:
    if client_id is None:
        raise _OAuthConfigurationError("GOOGLE_OAUTH_CLIENT_ID_MISSING")
    body = urlencode(
        {
            "client_id": client_id,
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
    def __init__(self, *, state: GoogleWorkspaceCredentialProvider, expected_state: str) -> None:
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
                    )
                    outer._state.keyring.put(
                        GOOGLE_REFRESH_TOKEN_KEY, refresh_token.encode("utf-8")
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


__all__ = ["GoogleOAuthSettings", "GoogleWorkspaceCredentialProvider"]
