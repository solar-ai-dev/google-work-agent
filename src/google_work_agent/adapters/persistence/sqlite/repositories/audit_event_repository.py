"""SQLite audit repository with persistence-side secret sanitization."""

import sqlite3
from dataclasses import replace
from json import loads
from typing import cast

from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.ports.persistence.audit_event_repository import (
    AuditEventCursor,
    PersistedAuditEventRecord,
)
from google_work_agent.ports.system.contracts.observability import (
    EventCategory,
    ObservabilityContext,
    Severity,
    create_event_envelope,
    sanitize_persistent_event_json,
    serialize_event_envelope,
)


class SqliteAuditEventRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def append(self, event: AuditEventRecord) -> None:
        event = replace(event, metadata_json=sanitize_persistent_event_json(event.metadata_json))
        raw = event.metadata_json
        try:
            payload = loads(raw)
        except Exception:
            payload = {"raw": raw}
        if not (
            isinstance(payload, dict) and "schema_version" in payload and "attributes" in payload
        ):
            attrs = (
                {str(k): cast(object, v) for k, v in payload.items()}
                if isinstance(payload, dict)
                else {"value": cast(object, payload)}
            )
            raw = serialize_event_envelope(
                create_event_envelope(
                    event_name=event.event_type,
                    event_category=EventCategory.DOMAIN,
                    occurred_at_ms=event.created_at_ms,
                    severity=Severity.INFO,
                    component="audit_event_repository",
                    environment="test",
                    release_version="dev",
                    correlation=ObservabilityContext(
                        run_id=event.run_id, action_id=event.action_id
                    ),
                    attributes=attrs,
                    result_code=event.outcome,
                    status=None,
                    duration_ms=None,
                )
            )
        self._connection.execute(
            "INSERT INTO audit_events (account_id, run_id, action_id, actor_type, actor_id, actor_display, event_type, outcome, metadata_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",  # noqa: E501
            (
                event.account_id,
                event.run_id,
                event.action_id,
                event.actor_type,
                event.actor_id,
                event.actor_display,
                event.event_type,
                event.outcome,
                raw,
                event.created_at_ms,
            ),
        )

    @staticmethod
    def _record(r: sqlite3.Row) -> PersistedAuditEventRecord:
        return PersistedAuditEventRecord(
            id=int(r["id"]),
            account_id=None if r["account_id"] is None else str(r["account_id"]),
            run_id=None if r["run_id"] is None else str(r["run_id"]),
            action_id=None if r["action_id"] is None else str(r["action_id"]),
            actor_type=str(r["actor_type"]),
            actor_id=str(r["actor_id"]),
            actor_display=None if r["actor_display"] is None else str(r["actor_display"]),
            event_type=str(r["event_type"]),
            outcome=str(r["outcome"]),
            metadata_json=str(r["metadata_json"]),
            created_at_ms=int(r["created_at_ms"]),
        )

    def list_page(
        self, cursor: AuditEventCursor | None, limit: int
    ) -> tuple[PersistedAuditEventRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        run_id = None if cursor is None else cursor.run_id
        action_id = None if cursor is None else cursor.action_id
        cursor_after = None if cursor is None else cursor.after_id
        rows = self._connection.execute(
            "SELECT id, account_id, run_id, action_id, actor_type, actor_id, actor_display, event_type, outcome, metadata_json, created_at_ms FROM audit_events WHERE (? IS NULL OR run_id=?) AND (? IS NULL OR action_id=?) AND (? IS NULL OR id>?) ORDER BY id ASC LIMIT ?;",  # noqa: E501
            (run_id, run_id, action_id, action_id, cursor_after, cursor_after, limit),
        ).fetchall()
        return tuple(self._record(r) for r in rows)

    def purge_before(self, timestamp_ms: int) -> int:
        return int(
            self._connection.execute(
                "DELETE FROM audit_events WHERE created_at_ms < ?;", (timestamp_ms,)
            ).rowcount
        )
