"""SQLite trace repository with persistence-side secret sanitization."""
import sqlite3
from dataclasses import replace
from json import loads
from typing import cast
from google_work_agent.application.observability import EventCategory, ObservabilityContext, Severity, create_event_envelope, sanitize_persistent_event_json, serialize_event_envelope
from google_work_agent.ports.models import PersistedTraceEventRecord, TraceEventRecord

class SQLiteTraceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection=connection
    def append(self, event: TraceEventRecord) -> None: self.add(event)
    def add(self, event: TraceEventRecord) -> None:
        event=replace(event, payload_json=sanitize_persistent_event_json(event.payload_json))
        raw=event.payload_json
        try: payload=loads(raw)
        except Exception: payload={"raw":raw}
        if not (isinstance(payload,dict) and "schema_version" in payload and "attributes" in payload):
            attrs={str(k):cast(object,v) for k,v in payload.items()} if isinstance(payload,dict) else {"value":cast(object,payload)}
            raw=serialize_event_envelope(create_event_envelope(event_name=event.event_type,event_category=EventCategory.DOMAIN,occurred_at_ms=event.created_at_ms,severity=Severity.INFO,component="trace_repository",environment="test",release_version="dev",correlation=ObservabilityContext(run_id=event.run_id,action_id=event.action_id),attributes=attrs,result_code=None,status=event.status,duration_ms=event.duration_ms))
        self._connection.execute("INSERT INTO trace_events (run_id, action_id, event_type, status, duration_ms, payload_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?);", (event.run_id,event.action_id,event.event_type,event.status,event.duration_ms,raw,event.created_at_ms))
    @staticmethod
    def _record(r: sqlite3.Row) -> PersistedTraceEventRecord:
        return PersistedTraceEventRecord(id=int(r["id"]),run_id=str(r["run_id"]),action_id=None if r["action_id"] is None else str(r["action_id"]),event_type=str(r["event_type"]),status=None if r["status"] is None else str(r["status"]),duration_ms=None if r["duration_ms"] is None else int(r["duration_ms"]),payload_json=str(r["payload_json"]),created_at_ms=int(r["created_at_ms"]))
    def list_by_run_after_cursor(self, *, run_id: str, cursor_after: int | None, limit: int=100) -> tuple[PersistedTraceEventRecord,...]:
        rows=self._connection.execute("SELECT id, run_id, action_id, event_type, status, duration_ms, payload_json, created_at_ms FROM trace_events WHERE run_id=? AND (? IS NULL OR id>?) ORDER BY id ASC LIMIT ?;", (run_id,cursor_after,cursor_after,limit)).fetchall(); return tuple(self._record(r) for r in rows)
    def list_before_retention_cutoff(self, *, cutoff_ms: int, limit: int) -> tuple[PersistedTraceEventRecord,...]:
        rows=self._connection.execute("SELECT id, run_id, action_id, event_type, status, duration_ms, payload_json, created_at_ms FROM trace_events WHERE created_at_ms < ? ORDER BY id ASC LIMIT ?;", (cutoff_ms,limit)).fetchall(); return tuple(self._record(r) for r in rows)
    def purge_before_cutoff(self, *, cutoff_ms: int, limit: int) -> int:
        return int(self._connection.execute("DELETE FROM trace_events WHERE id IN (SELECT id FROM trace_events WHERE created_at_ms < ? ORDER BY id ASC LIMIT ?);", (cutoff_ms,limit)).rowcount)
