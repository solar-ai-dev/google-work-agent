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


@dataclass(frozen=True, slots=True)
class AuditEventCursor:
    run_id: str | None = None
    action_id: str | None = None
    after_id: int | None = None


class AuditEventRepository(Protocol):
    def append(self, event: AuditEventRecord) -> None: ...
    def list_page(
        self, cursor: AuditEventCursor | None, limit: int
    ) -> tuple[PersistedAuditEventRecord, ...]: ...
    def purge_before(self, timestamp_ms: int) -> int: ...
