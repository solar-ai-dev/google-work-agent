"""Audit-event domain model."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AuditEvent:
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
