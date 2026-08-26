"""Persistence-side defense in depth for Trace/Audit secret boundaries."""

from __future__ import annotations

from dataclasses import replace

from google_work_agent.adapters.persistence.sqlite.repositories.audit_repository import (
    SQLiteAuditRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.trace_repository import (
    SQLiteTraceRepository,
)
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.observability_events import sanitize_persistent_event_json


class SecretBoundaryAuditRepository(SQLiteAuditRepository):
    """Audit repository that sanitizes event JSON immediately before SQLite persistence."""

    def add(self, event: AuditEventRecord) -> None:
        super().add(
            replace(
                event,
                metadata_json=sanitize_persistent_event_json(event.metadata_json),
            )
        )


class SecretBoundaryTraceRepository(SQLiteTraceRepository):
    """Trace repository that sanitizes event JSON immediately before SQLite persistence."""

    def add(self, event: TraceEventRecord) -> None:
        super().add(
            replace(
                event,
                payload_json=sanitize_persistent_event_json(event.payload_json),
            )
        )
