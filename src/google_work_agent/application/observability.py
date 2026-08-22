"""Application observability emission, sinks, and retention services."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.ports import (
    AuditEventRecord,
    MaintenanceGate,
    MaintenanceWindow,
    OperationalLogRecord,
    OperationalLogSink,
    TraceEventRecord,
    UnitOfWork,
)
from google_work_agent.ports.observability import (
    FORBIDDEN_CONTENT_KEYS,
    FORBIDDEN_KEY_FRAGMENTS,
    FORBIDDEN_VALUE_FRAGMENTS,
    MAX_ATTRIBUTE_BYTES,
    MAX_COLLECTION_ITEMS,
    MAX_DEPTH,
    MAX_STRING_BYTES,
    SCHEMA_VERSION,
    EventCategory,
    EventEnvelope,
    EventValidationError,
    ObservabilityContext,
    ObservabilityError,
    PayloadTooLargeError,
    SanitizationError,
    SanitizedAttributes,
    Severity,
    assert_persistence_value_secret_free,
    create_event_envelope,
    is_forbidden_persistence_key,
    sanitize_event_attributes,
    sanitize_persistent_event_json,
    serialize_event_envelope,
)

TRACE_RETENTION_MS = 30 * 24 * 60 * 60 * 1000
AUDIT_RETENTION_MS = 90 * 24 * 60 * 60 * 1000
OPERATIONAL_LOG_RETENTION_MS = 14 * 24 * 60 * 60 * 1000
MAX_PURGE_BATCH = 500
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
MAX_LOG_DIR_BYTES = 200 * 1024 * 1024


class TraceWriteError(ObservabilityError):
    """Raised when a required trace write fails."""


class AuditWriteError(ObservabilityError):
    """Raised when a required audit write fails."""


class OperationalLogWriteError(ObservabilityError):
    """Raised when operational JSONL persistence fails."""


class PurgeBlockedError(ObservabilityError):
    """Raised when retention purge is blocked by maintenance state."""


@dataclass(frozen=True, slots=True)
class EventEmissionPolicy:
    allow_audit: bool
    allow_trace: bool
    required_audit: bool = True
    required_trace: bool = False


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
    except Exception as error:  # pragma: no cover - integration fault tests
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
    """UTF-8 JSONL sink with secret scrubbing, rotation, retention, and size caps."""

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
        event_json = sanitize_persistent_event_json(record.event_json)
        self._directory.mkdir(parents=True, exist_ok=True)
        self._cleanup_expired_files()
        path = self._select_target_file()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event_json)
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


@dataclass(frozen=True, slots=True)
class PurgeResult:
    trace_deleted: int
    audit_deleted: int
    audit_event_written: bool


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


def _is_forbidden_key(key: str) -> bool:
    """Backward-compatible alias for the centralized persistence-key classifier."""

    return is_forbidden_persistence_key(key)
