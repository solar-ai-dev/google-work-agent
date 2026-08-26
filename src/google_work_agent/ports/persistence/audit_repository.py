"""Audit-event persistence port."""

from dataclasses import dataclass
from typing import Protocol

from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord


@dataclass(frozen=True, slots=True)
class PersistedAuditEventRecord:
    id: int
    account_id: str | None
    run_id: str | None
    action_id: str | None
    actor_type: str
    actor_id: str
    actor_display: str | None
    event_type: str
    outcome: str
    metadata_json: str
    created_at_ms: int


class AuditRepository(Protocol):
    def append(self, event: AuditEventRecord) -> None: ...
    def add(self, event: AuditEventRecord) -> None: ...
    def list_by_aggregate(
        self,
        *,
        run_id: str | None,
        action_id: str | None = None,
        cursor_after: int | None = None,
        limit: int = 100,
    ) -> tuple[PersistedAuditEventRecord, ...]: ...
    def list_after_cursor(
        self, *, cursor_after: int | None, limit: int = 100
    ) -> tuple[PersistedAuditEventRecord, ...]: ...
    def list_before_retention_cutoff(
        self, *, cutoff_ms: int, limit: int
    ) -> tuple[PersistedAuditEventRecord, ...]: ...
    def purge_before_cutoff(self, *, cutoff_ms: int, limit: int) -> int: ...
