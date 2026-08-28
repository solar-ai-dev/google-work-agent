"""Trace-event-owner-local observability emission support."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.events.observability import (
    MaintenanceWindow,
    OperationalLogRecord,
    OperationalLogSink,
)
from google_work_agent.ports.events.observability_events import (
    EventCategory,
    EventEnvelope,
    EventValidationError,
    ObservabilityContext,
    ObservabilityError,
    Severity,
    create_event_envelope,
    sanitize_persistent_event_json,
    serialize_event_envelope,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

OPERATIONAL_LOG_RETENTION_MS = 14 * 24 * 60 * 60 * 1000
MAX_LOG_FILE_BYTES = 10 * 1024 * 1024
MAX_LOG_DIR_BYTES = 200 * 1024 * 1024


class TraceWriteError(ObservabilityError):
    """Raised when a required trace write fails."""


class AuditWriteError(ObservabilityError):
    """Raised when a required audit write fails."""


class OperationalLogWriteError(ObservabilityError):
    """Raised when operational JSONL persistence fails."""


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
