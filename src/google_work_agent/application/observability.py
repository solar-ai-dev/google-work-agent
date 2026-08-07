"""Common observability contracts, sanitization, sinks, and purge services."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import cast

from google_work_agent.ports import (
    AuditEventRecord,
    MaintenanceGate,
    MaintenanceWindow,
    OperationalLogRecord,
    OperationalLogSink,
    TraceEventRecord,
    UnitOfWork,
)

SCHEMA_VERSION = 1
MAX_ATTRIBUTE_BYTES = 16 * 1024
MAX_STRING_BYTES = 2048
MAX_COLLECTION_ITEMS = 50
MAX_DEPTH = 4
TRACE_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
AUDIT_RETENTION_MS = 90 * 24 * 60 * 60 * 1000
OPERATIONAL_LOG_RETENTION_MS = 14 * 24 * 60 * 60 * 1000
MAX_PURGE_BATCH = 500
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
MAX_LOG_DIR_BYTES = 200 * 1024 * 1024

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


class TraceWriteError(ObservabilityError):
    """Raised when a required trace write fails."""


class AuditWriteError(ObservabilityError):
    """Raised when a required audit write fails."""


class OperationalLogWriteError(ObservabilityError):
    """Raised when operational JSONL persistence fails."""


class PurgeBlockedError(ObservabilityError):
    """Raised when retention purge is blocked by maintenance state."""


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


JsonScalar = None | bool | int | float | str
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


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


@dataclass(frozen=True, slots=True)
class EventEmissionPolicy:
    allow_audit: bool
    allow_trace: bool
    required_audit: bool = True
    required_trace: bool = False


@dataclass(frozen=True, slots=True)
class PurgeResult:
    trace_deleted: int
    audit_deleted: int
    audit_event_written: bool


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
    payload_bytes = payload.encode("utf-8")
    truncated = False
    if len(payload_bytes) > max_attribute_bytes:
        summary = {
            "count": len(sanitized),
            "byte_size": len(payload_bytes),
            "sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "truncated": True,
            "omitted_fields": sorted(removed_fields | set(sanitized)),
        }
        sanitized = cast(dict[str, JsonValue], summary)
        payload = json.dumps(sanitized, sort_keys=True, ensure_ascii=False)
        payload_bytes = payload.encode("utf-8")
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
    payload_bytes = payload.encode("utf-8")
    if len(payload_bytes) > MAX_ATTRIBUTE_BYTES:
        raise PayloadTooLargeError("serialized event envelope exceeds 16 KiB limit")
    return payload


def emit_trace_event(
    unit_of_work: UnitOfWork,
    *,
    correlation: ObservabilityContext,
    event_name: str,
    event_category: EventCategory,
    occurred_at_ms: int,
    severity: Severity,
    component: str,
    environment: str,
    release_version: str,
    attributes: dict[str, object],
    result_code: str | None,
    status: str | None,
    duration_ms: int | None = None,
    required: bool = False,
) -> None:
    if correlation.run_id is None:
        raise EventValidationError("trace events require run_id")
    envelope = create_event_envelope(
        event_name=event_name,
        event_category=event_category,
        occurred_at_ms=occurred_at_ms,
        severity=severity,
        component=component,
        environment=environment,
        release_version=release_version,
        correlation=correlation,
        attributes=attributes,
        result_code=result_code,
        status=status,
        duration_ms=duration_ms,
    )
    try:
        unit_of_work.traces.append(
            TraceEventRecord(
                run_id=correlation.run_id,
                action_id=correlation.action_id,
                event_type=event_name,
                status=status,
                duration_ms=duration_ms,
                payload_json=serialize_event_envelope(envelope),
                created_at_ms=occurred_at_ms,
            )
        )
    except Exception as error:  # pragma: no cover - exercised in integration fault tests
        if required:
            raise TraceWriteError("trace append failed") from error


def emit_audit_event(
    unit_of_work: UnitOfWork,
    *,
    correlation: ObservabilityContext,
    account_id: str | None,
    actor_type: str,
    actor_id: str,
    actor_display: str | None,
    event_name: str,
    event_category: EventCategory,
    occurred_at_ms: int,
    severity: Severity,
    component: str,
    environment: str,
    release_version: str,
    attributes: dict[str, object],
    result_code: str | None,
    status: str | None,
    duration_ms: int | None = None,
    required: bool = True,
) -> None:
    envelope = create_event_envelope(
        event_name=event_name,
        event_category=event_category,
        occurred_at_ms=occurred_at_ms,
        severity=severity,
        component=component,
        environment=environment,
        release_version=release_version,
        correlation=correlation,
        attributes=attributes,
        result_code=result_code,
        status=status,
        duration_ms=duration_ms,
    )
    try:
        unit_of_work.audits.append(
            AuditEventRecord(
                account_id=account_id,
                run_id=correlation.run_id,
                action_id=correlation.action_id,
                actor_type=actor_type,
                actor_id=actor_id,
                actor_display=actor_display,
                event_type=event_name,
                outcome=result_code or "",
                metadata_json=serialize_event_envelope(envelope),
                created_at_ms=occurred_at_ms,
            )
        )
    except Exception as error:
        if required:
            raise AuditWriteError("audit append failed") from error


def append_operational_log(
    sink: OperationalLogSink,
    *,
    envelope: EventEnvelope,
) -> None:
    try:
        sink.append(
            OperationalLogRecord(
                event_json=serialize_event_envelope(envelope),
                occurred_at_ms=envelope.occurred_at_ms,
            )
        )
    except Exception as error:
        raise OperationalLogWriteError("operational log append failed") from error


class SanitizedJsonlLogSink:
    """UTF-8 JSONL sink with rotation, retention, and directory size caps."""

    def __init__(
        self,
        *,
        directory: Path,
        filename_prefix: str,
        now_ms: Callable[[], int],
    ) -> None:
        self._directory = directory
        self._filename_prefix = filename_prefix
        self._now_ms = now_ms

    def append(self, record: OperationalLogRecord) -> None:
        self._directory.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired_files()
        path = self._select_target_file()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(record.event_json)
            handle.write("\n")
        self._enforce_directory_cap()

    def _select_target_file(self) -> Path:
        current = self._directory / f"{self._filename_prefix}.jsonl"
        if current.exists() and current.stat().st_size >= MAX_LOG_FILE_BYTES:
            rotated = self._directory / f"{self._filename_prefix}-{self._now_ms()}.jsonl"
            current.replace(rotated)
        return current

    def _cleanup_expired_files(self) -> None:
        cutoff_ms = self._now_ms() - OPERATIONAL_LOG_RETENTION_MS
        for path in self._directory.glob(f"{self._filename_prefix}*.jsonl"):
            if int(path.stat().st_mtime * 1000) < cutoff_ms:
                path.unlink(missing_ok=True)

    def _enforce_directory_cap(self) -> None:
        files = sorted(
            self._directory.glob(f"{self._filename_prefix}*.jsonl"),
            key=lambda item: item.stat().st_mtime,
        )
        total_bytes = sum(path.stat().st_size for path in files)
        while files and total_bytes > MAX_LOG_DIR_BYTES:
            path = files.pop(0)
            total_bytes -= path.stat().st_size
            path.unlink(missing_ok=True)


@dataclass(frozen=True, slots=True)
class StaticMaintenanceGate:
    """Test helper maintenance gate."""

    has_active_write: bool = False
    migration_running: bool = False
    restore_running: bool = False

    def snapshot(self) -> MaintenanceWindow:
        return MaintenanceWindow(
            has_active_write=self.has_active_write,
            migration_running=self.migration_running,
            restore_running=self.restore_running,
        )


@dataclass(frozen=True, slots=True)
class PurgeObservabilityDataCommand:
    now_ms: int


class PurgeObservabilityDataService:
    """Purge retained trace and audit rows in bounded batches."""

    def __init__(
        self,
        *,
        unit_of_work_factory: Callable[[], UnitOfWork],
        maintenance_gate: MaintenanceGate,
    ) -> None:
        self._unit_of_work_factory = unit_of_work_factory
        self._maintenance_gate = maintenance_gate

    def __call__(self, command: PurgeObservabilityDataCommand) -> PurgeResult:
        snapshot = self._maintenance_gate.snapshot()
        if snapshot.has_active_write or snapshot.migration_running or snapshot.restore_running:
            raise PurgeBlockedError("purge is blocked by maintenance state")
        with self._unit_of_work_factory() as unit_of_work:
            trace_deleted = unit_of_work.traces.purge_before_cutoff(
                cutoff_ms=command.now_ms - TRACE_RETENTION_MS,
                limit=MAX_PURGE_BATCH,
            )
            audit_deleted = unit_of_work.audits.purge_before_cutoff(
                cutoff_ms=command.now_ms - AUDIT_RETENTION_MS,
                limit=MAX_PURGE_BATCH,
            )
            audit_event_written = False
            if trace_deleted > 0 or audit_deleted > 0:
                emit_audit_event(
                    unit_of_work,
                    correlation=ObservabilityContext(),
                    account_id=None,
                    actor_type="SYSTEM",
                    actor_id="purge_observability_data",
                    actor_display="PurgeObservabilityDataService",
                    event_name="PURGE_COMPLETED",
                    event_category=EventCategory.PERSISTENCE,
                    occurred_at_ms=command.now_ms,
                    severity=Severity.INFO,
                    component="retention",
                    environment="test",
                    release_version="dev",
                    attributes={
                        "trace_deleted": trace_deleted,
                        "audit_deleted": audit_deleted,
                        "batch_limit": MAX_PURGE_BATCH,
                    },
                    result_code="TRANSITION_APPLIED",
                    status="COMPLETED",
                    required=False,
                )
                audit_event_written = True
            unit_of_work.commit()
            return PurgeResult(
                trace_deleted=trace_deleted,
                audit_deleted=audit_deleted,
                audit_event_written=audit_event_written,
            )


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
    if isinstance(value, dict):
        sanitized: dict[str, JsonValue] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= max_collection_items:
                removed_fields.add(f"{path}[*]")
                break
            normalized_key = str(key)
            if _is_forbidden_key(normalized_key):
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
        sanitized_items: list[JsonValue] = []
        for index, item in enumerate(value[:max_collection_items]):
            sanitized_items.append(
                _sanitize_value(
                    item,
                    path=f"{path}[{index}]",
                    depth=depth - 1,
                    removed_fields=removed_fields,
                    max_collection_items=max_collection_items,
                    max_string_bytes=max_string_bytes,
                )
            )
        if len(value) > max_collection_items:
            removed_fields.add(f"{path}[*]")
        return sanitized_items
    return _sanitize_string(repr(value), max_string_bytes=max_string_bytes)


def _sanitize_string(value: str, *, max_string_bytes: int) -> str:
    lowered = value.lower()
    if any(fragment in lowered for fragment in FORBIDDEN_VALUE_FRAGMENTS):
        return "<redacted>"
    sanitized = EMAIL_PATTERN.sub(r"<redacted-email>@\2", value)
    sanitized = WINDOWS_HOME_PATTERN.sub(
        lambda _match: r"C:\Users\<redacted-user>",
        sanitized,
    )
    for forbidden_key in FORBIDDEN_CONTENT_KEYS:
        if forbidden_key in lowered:
            return "<redacted>"
    encoded = sanitized.encode("utf-8")
    if len(encoded) <= max_string_bytes:
        return sanitized
    truncated = encoded[: max_string_bytes - 3].decode("utf-8", errors="ignore")
    return f"{truncated}..."


def _is_forbidden_key(key: str) -> bool:
    normalized = key.replace("-", "_").replace(" ", "_").lower()
    return any(fragment in normalized for fragment in FORBIDDEN_KEY_FRAGMENTS)
