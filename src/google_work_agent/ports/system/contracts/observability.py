"""System-boundary observability contracts and sanitization policy."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from enum import Enum, StrEnum
from typing import Protocol, cast

SCHEMA_VERSION = 1
MAX_ATTRIBUTE_BYTES = 16 * 1024
MAX_STRING_BYTES = 2048
MAX_COLLECTION_ITEMS = 50
MAX_DEPTH = 4


@dataclass(frozen=True, slots=True)
class OperationalLogRecord:
    """One sanitized operational log line."""

    event_json: str
    occurred_at_ms: int


class OperationalLogSink(Protocol):
    """Append-only sink for already-sanitized operational events."""

    def append(self, record: OperationalLogRecord) -> None: ...


FORBIDDEN_KEY_FRAGMENTS = {
    "access_token",
    "refresh_token",
    "id_token",
    "api_key",
    "authorization",
    "cookie",
    "set_cookie",
    "bootstrap_secret",
    "session_id",
    "session_secret",
    "pkce_verifier",
    "oauth_code",
    "client_secret",
    "claim_token",
    "service_session_key",
    "private_key",
    "password",
    "credential",
}
_SECRET_KEY_EXACT = {
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "apikey",
    "authorization",
    "proxyauthorization",
    "authorizationheader",
    "cookie",
    "setcookie",
    "cookieheader",
    "bootstrapsecret",
    "sessionid",
    "sessionsecret",
    "pkce",
    "pkceverifier",
    "codeverifier",
    "oauthcode",
    "clientsecret",
    "claimtoken",
    "servicesessionkey",
    "privatekey",
    "password",
    "secret",
    "credential",
    "credentials",
    "connectorcredential",
    "connectorcredentials",
    "rawauth",
    "mcpauth",
    "providerauth",
    "connectorauth",
    "authentication",
    "authmaterial",
    "pagetoken",
    "nextpagetoken",
    "continuationtoken",
    "attachmentbytes",
    "rawattachment",
    "providerpayload",
    "rawproviderresponse",
    "rawproviderrequest",
    "mcprequest",
    "mcpresponse",
}
_SECRET_KEY_SUFFIXES = (
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "apikey",
    "clientsecret",
    "sessionsecret",
    "bootstrapsecret",
    "codeverifier",
    "pkceverifier",
    "claimtoken",
    "servicesessionkey",
    "privatekey",
    "credential",
    "credentials",
    "pagetoken",
    "nextpagetoken",
    "continuationtoken",
    "attachmentbytes",
    "rawproviderresponse",
    "rawproviderrequest",
    "providerpayload",
)
FORBIDDEN_VALUE_FRAGMENTS = {
    "bearer ",
    "canary_refresh_token",
    "canary_api_key",
    "canary_claim_token",
    "canary_bootstrap",
    "canary_session",
    "canary_pkce",
    "canary_authorization",
    "canary_gmail_body",
    "canary_prompt",
    "canary_private_key",
    "canary_llm_api_key",
    "canary_completion",
    "canary_context",
    "authorization:",
    "cookie:",
    "begin private key",
    "gmail body",
    "prompt",
}
FORBIDDEN_CONTENT_KEYS = {
    "gmail_body",
    "draft_body",
    "prompt",
    "completion",
    "approval_snapshot",
    "mcp_request",
    "mcp_response",
    "google_resource",
}
_FORBIDDEN_CONTENT_KEYS_COMPACT = {
    "gmailbody",
    "draftbody",
    "prompt",
    "completion",
    "approvalsnapshot",
    "mcprequest",
    "mcpresponse",
    "googleresource",
}
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)(?:access[_-]?token|refresh[_-]?token|api[_-]?key|client[_-]?secret|"
    r"session[_-]?secret|bootstrap[_-]?secret|code[_-]?verifier|pkce[_-]?verifier)"
    r"\s*[:=]\s*\S+"
)
_AUTH_HEADER_PATTERN = re.compile(
    r"(?i)(?:authorization|proxy-authorization|cookie|set-cookie)\s*[:=]\s*\S+"
)
_AUTH_SCHEME_PATTERN = re.compile(r"(?i)\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{4,}")
EMAIL_PATTERN = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
WINDOWS_HOME_PATTERN = re.compile(r"[A-Za-z]:\\Users\\[^\\]+", re.IGNORECASE)


class ObservabilityError(RuntimeError):
    """Base error for observability operations."""


class EventValidationError(ObservabilityError):
    """Raised when an event envelope is invalid."""


class SanitizationError(ObservabilityError):
    """Raised when attributes cannot be sanitized safely."""


class PayloadTooLargeError(ObservabilityError):
    """Raised when a sanitized payload cannot fit the schema limit."""


class Severity(StrEnum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class EventCategory(StrEnum):
    LIFECYCLE = "LIFECYCLE"
    API = "API"
    WORKFLOW = "WORKFLOW"
    AGENT = "AGENT"
    RETRIEVAL = "RETRIEVAL"
    LLM = "LLM"
    DOMAIN = "DOMAIN"
    MCP = "MCP"
    GOOGLE = "GOOGLE"
    VERIFICATION = "VERIFICATION"
    SECURITY = "SECURITY"
    PERSISTENCE = "PERSISTENCE"
    INSTALLER = "INSTALLER"
    DIAGNOSTIC = "DIAGNOSTIC"


@dataclass(frozen=True, slots=True)
class ObservabilityContext:
    app_instance_id: str | None = None
    service_instance_id: str | None = None
    request_id: str | None = None
    command_id: str | None = None
    conversation_id: str | None = None
    run_id: str | None = None
    langgraph_thread_id: str | None = None
    plan_id: str | None = None
    action_id: str | None = None
    approval_id: str | None = None
    execution_attempt_id: str | None = None
    verification_id: str | None = None
    llm_call_id: str | None = None
    mcp_request_id: str | None = None
    provider_request_id: str | None = None
    google_request_id: str | None = None


class LLMEventRecorder(Protocol):
    """Record one sanitized LLM boundary event."""

    def record(
        self,
        *,
        event_name: str,
        severity: Severity,
        correlation: ObservabilityContext,
        attributes: Mapping[str, object],
        result_code: str | None = None,
        status: str | None = None,
        duration_ms: int | None = None,
    ) -> None: ...


type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class EventEnvelope:
    schema_version: int
    event_name: str
    event_category: EventCategory
    occurred_at_ms: int
    severity: Severity
    component: str
    environment: str
    release_version: str
    correlation: ObservabilityContext
    result_code: str | None
    status: str | None
    duration_ms: int | None
    attributes: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class SanitizedAttributes:
    values: dict[str, JsonValue]
    removed_fields: tuple[str, ...]
    truncated: bool
    byte_size: int


def sanitize_event_attributes(
    attributes: dict[str, object],
    *,
    max_depth: int = MAX_DEPTH,
    max_collection_items: int = MAX_COLLECTION_ITEMS,
    max_string_bytes: int = MAX_STRING_BYTES,
    max_attribute_bytes: int = MAX_ATTRIBUTE_BYTES,
) -> SanitizedAttributes:
    removed_fields: set[str] = set()
    sanitized = cast(
        dict[str, JsonValue],
        _sanitize_value(
            attributes,
            path="$",
            depth=max_depth,
            removed_fields=removed_fields,
            max_collection_items=max_collection_items,
            max_string_bytes=max_string_bytes,
        ),
    )
    payload = json.dumps(sanitized, sort_keys=True, ensure_ascii=False)
    payload_bytes = payload.encode()
    truncated = False
    if len(payload_bytes) > max_attribute_bytes:
        sanitized = {
            "count": len(sanitized),
            "byte_size": len(payload_bytes),
            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "truncated": True,
            "omitted_fields": cast(list[JsonValue], sorted(removed_fields | set(sanitized))),
        }
        payload_bytes = json.dumps(sanitized, sort_keys=True, ensure_ascii=False).encode()
        truncated = True
        if len(payload_bytes) > max_attribute_bytes:
            raise PayloadTooLargeError("sanitized payload exceeds 16 KiB limit")
    return SanitizedAttributes(
        values=sanitized,
        removed_fields=tuple(sorted(removed_fields)),
        truncated=truncated,
        byte_size=len(payload_bytes),
    )


def create_event_envelope(
    *,
    event_name: str,
    event_category: EventCategory,
    occurred_at_ms: int,
    severity: Severity,
    component: str,
    environment: str,
    release_version: str,
    correlation: ObservabilityContext,
    attributes: dict[str, object],
    result_code: str | None = None,
    status: str | None = None,
    duration_ms: int | None = None,
) -> EventEnvelope:
    if occurred_at_ms < 0:
        raise EventValidationError("occurred_at_ms must be non-negative")
    if duration_ms is not None and duration_ms < 0:
        raise EventValidationError("duration_ms must be non-negative")
    if not event_name.strip():
        raise EventValidationError("event_name must not be blank")
    if not component.strip():
        raise EventValidationError("component must not be blank")
    sanitized = sanitize_event_attributes(attributes)
    return EventEnvelope(
        schema_version=SCHEMA_VERSION,
        event_name=event_name,
        event_category=event_category,
        occurred_at_ms=occurred_at_ms,
        severity=severity,
        component=component,
        environment=environment,
        release_version=release_version,
        correlation=correlation,
        result_code=result_code,
        status=status,
        duration_ms=duration_ms,
        attributes=sanitized.values,
    )


def serialize_event_envelope(envelope: EventEnvelope) -> str:
    payload = json.dumps(asdict(envelope), sort_keys=True, ensure_ascii=False)
    if len(payload.encode()) > MAX_ATTRIBUTE_BYTES:
        raise PayloadTooLargeError("serialized event envelope exceeds 16 KiB limit")
    return payload


def sanitize_persistent_event_json(raw: str) -> str:
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as error:
        raise SanitizationError("persistent event payload must be valid JSON") from error
    cleaned = _scrub_persistent_json_value(value)
    return json.dumps(cleaned, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def is_forbidden_persistence_key(key: object) -> bool:
    compact = _compact_key(key)
    if compact in _SECRET_KEY_EXACT or compact in _FORBIDDEN_CONTENT_KEYS_COMPACT:
        return True
    return any(compact.endswith(suffix) for suffix in _SECRET_KEY_SUFFIXES)


def assert_persistence_value_secret_free(value: object) -> None:
    _assert_secret_free(value, path="$", seen=set())


def _sanitize_value(
    value: object,
    *,
    path: str,
    depth: int,
    removed_fields: set[str],
    max_collection_items: int,
    max_string_bytes: int,
) -> JsonValue:
    if depth < 0:
        removed_fields.add(path)
        return "<omitted-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return cast(JsonScalar, value)
    if isinstance(value, str):
        return _sanitize_string(value, max_string_bytes=max_string_bytes)
    if isinstance(value, Enum):
        return _sanitize_value(
            value.value,
            path=path,
            depth=depth,
            removed_fields=removed_fields,
            max_collection_items=max_collection_items,
            max_string_bytes=max_string_bytes,
        )
    if isinstance(value, Mapping):
        sanitized: dict[str, JsonValue] = {}
        attachment_projection = _looks_like_attachment_projection(value)
        for index, (key, item) in enumerate(value.items()):
            if index >= max_collection_items:
                removed_fields.add(f"{path}[*]")
                break
            normalized_key = str(key)
            if is_forbidden_persistence_key(normalized_key) or (
                attachment_projection and _compact_key(normalized_key) == "data"
            ):
                removed_fields.add(f"{path}.{normalized_key}")
                continue
            sanitized[normalized_key] = _sanitize_value(
                item,
                path=f"{path}.{normalized_key}",
                depth=depth - 1,
                removed_fields=removed_fields,
                max_collection_items=max_collection_items,
                max_string_bytes=max_string_bytes,
            )
        return sanitized
    if isinstance(value, list | tuple):
        items = [
            _sanitize_value(
                item,
                path=f"{path}[{index}]",
                depth=depth - 1,
                removed_fields=removed_fields,
                max_collection_items=max_collection_items,
                max_string_bytes=max_string_bytes,
            )
            for index, item in enumerate(value[:max_collection_items])
        ]
        if len(value) > max_collection_items:
            removed_fields.add(f"{path}[*]")
        return items
    removed_fields.add(path)
    return "<omitted-object>"


def _sanitize_string(value: str, *, max_string_bytes: int) -> str:
    lowered = value.lower()
    if _contains_secret_text(value) or any(
        fragment in lowered for fragment in FORBIDDEN_VALUE_FRAGMENTS
    ):
        return "<redacted>"
    sanitized = EMAIL_PATTERN.sub(r"<redacted-email>@\2", value)
    sanitized = WINDOWS_HOME_PATTERN.sub(lambda _: r"C:\Users\<redacted-user>", sanitized)
    encoded = sanitized.encode()
    if len(encoded) <= max_string_bytes:
        return sanitized
    return f"{encoded[: max_string_bytes - 3].decode(errors='ignore')}..."


def _scrub_persistent_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, int, float)):
        return cast(JsonScalar, value)
    if isinstance(value, str):
        lowered = value.lower()
        if _contains_secret_text(value) or any(
            fragment in lowered for fragment in FORBIDDEN_VALUE_FRAGMENTS
        ):
            return "<redacted>"
        return value
    if isinstance(value, list):
        return [_scrub_persistent_json_value(item) for item in value]
    if isinstance(value, dict):
        cleaned: dict[str, JsonValue] = {}
        attachment_projection = _looks_like_attachment_projection(value)
        for key, item in value.items():
            normalized_key = str(key)
            if is_forbidden_persistence_key(normalized_key) or (
                attachment_projection and _compact_key(normalized_key) == "data"
            ):
                continue
            cleaned[normalized_key] = _scrub_persistent_json_value(item)
        return cleaned
    raise SanitizationError("persistent event JSON contains an unsupported value")


def _assert_secret_free(value: object, *, path: str, seen: set[int]) -> None:
    if value is None or isinstance(value, (bool, int, float)):
        return
    if isinstance(value, str):
        if _contains_secret_text(value):
            raise SanitizationError(f"secret material rejected at {path}")
        return
    if isinstance(value, Enum):
        _assert_secret_free(value.value, path=path, seen=seen)
        return
    identity = id(value)
    if identity in seen:
        return
    seen.add(identity)
    try:
        if isinstance(value, Mapping):
            attachment_projection = _looks_like_attachment_projection(value)
            for key, item in value.items():
                if is_forbidden_persistence_key(key) or (
                    attachment_projection and _compact_key(key) == "data"
                ):
                    raise SanitizationError(f"secret field rejected at {path}.{key}")
                _assert_secret_free(item, path=f"{path}.{key}", seen=seen)
            return
        if isinstance(value, (list, tuple, set, frozenset)):
            for index, item in enumerate(value):
                _assert_secret_free(item, path=f"{path}[{index}]", seen=seen)
            return
        if is_dataclass(value) and not isinstance(value, type):
            for item_field in fields(value):
                if is_forbidden_persistence_key(item_field.name):
                    raise SanitizationError(f"secret field rejected at {path}.{item_field.name}")
                _assert_secret_free(
                    getattr(value, item_field.name),
                    path=f"{path}.{item_field.name}",
                    seen=seen,
                )
            return
        if hasattr(value, "model_dump") and callable(value.model_dump):
            _assert_secret_free(value.model_dump(), path=path, seen=seen)
            return
        try:
            attributes = vars(value)
        except TypeError as error:
            raise SanitizationError(
                f"opaque object cannot cross persistence boundary at {path}"
            ) from error
        _assert_secret_free(attributes, path=path, seen=seen)
    finally:
        seen.discard(identity)


def _contains_secret_text(value: str) -> bool:
    lowered = value.lower()
    return bool(
        _AUTH_SCHEME_PATTERN.search(value)
        or _AUTH_HEADER_PATTERN.search(value)
        or _SECRET_ASSIGNMENT_PATTERN.search(value)
        or "-----begin private key-----" in lowered
    )


def _looks_like_attachment_projection(value: Mapping[object, object]) -> bool:
    compact_keys = {_compact_key(key) for key in value}
    return "data" in compact_keys and bool({"filename", "mimetype", "attachmentid"} & compact_keys)


def _compact_key(value: object) -> str:
    return "".join(character for character in str(value).casefold() if character.isalnum())
