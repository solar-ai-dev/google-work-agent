"""SQLite resource-reference repository with connector-aware identity."""
import sqlite3
from google_work_agent.ports.models import ResourceRefRecord, ResourceSource, StoredResourceType

class SQLiteResourceRefRepository:
    _SELECT = "SELECT id, run_id, connector_id, source, resource_type, resource_id, parent_resource_id, canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms FROM resource_refs"
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection = connection
    @staticmethod
    def _record(row: sqlite3.Row) -> ResourceRefRecord:
        return ResourceRefRecord(id=str(row["id"]), run_id=str(row["run_id"]), connector_id=str(row["connector_id"]), source=ResourceSource(str(row["source"])), resource_type=StoredResourceType(str(row["resource_type"])), resource_id=str(row["resource_id"]), parent_resource_id=None if row["parent_resource_id"] is None else str(row["parent_resource_id"]), canonical_url=None if row["canonical_url"] is None else str(row["canonical_url"]), title=None if row["title"] is None else str(row["title"]), event_time_ms=None if row["event_time_ms"] is None else int(row["event_time_ms"]), version_token=None if row["version_token"] is None else str(row["version_token"]), metadata_json=str(row["metadata_json"]), captured_at_ms=int(row["captured_at_ms"]))
    def get_by_id(self, resource_ref_id: str) -> ResourceRefRecord | None:
        row = self._connection.execute(self._SELECT + " WHERE id = ?;", (resource_ref_id,)).fetchone(); return None if row is None else self._record(row)
    def get_by_unique_key(self, *, run_id: str, connector_id: str, resource_type: str, resource_id: str) -> ResourceRefRecord | None:
        if not connector_id: raise ValueError("resource reference lookup requires connector_id")
        row = self._connection.execute(self._SELECT + " WHERE run_id = ? AND connector_id = ? AND resource_type = ? AND resource_id = ?;", (run_id, connector_id, resource_type, resource_id)).fetchone(); return None if row is None else self._record(row)
    def upsert(self, record: ResourceRefRecord) -> None:
        if not record.connector_id: raise ValueError("resource reference persistence requires connector_id")
        self._connection.execute("""INSERT INTO resource_refs (id, run_id, connector_id, source, resource_type, resource_id, parent_resource_id, canonical_url, title, event_time_ms, version_token, metadata_json, captured_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(run_id, connector_id, resource_type, resource_id) DO UPDATE SET source=excluded.source, parent_resource_id=excluded.parent_resource_id, canonical_url=excluded.canonical_url, title=excluded.title, event_time_ms=excluded.event_time_ms, version_token=excluded.version_token, metadata_json=excluded.metadata_json, captured_at_ms=excluded.captured_at_ms;""", (record.id, record.run_id, record.connector_id, record.source.value, record.resource_type.value, record.resource_id, record.parent_resource_id, record.canonical_url, record.title, record.event_time_ms, record.version_token, record.metadata_json, record.captured_at_ms))
    def list_by_run(self, run_id: str) -> tuple[ResourceRefRecord, ...]:
        rows=self._connection.execute(self._SELECT + " WHERE run_id = ? ORDER BY connector_id, source, resource_type, resource_id;", (run_id,)).fetchall(); return tuple(self._record(r) for r in rows)
    def connector_id_for_resource_ref(self, resource_ref_id: str) -> str:
        record=self.get_by_id(resource_ref_id)
        if record is None: raise LookupError(f"resource ref not found: {resource_ref_id}")
        return record.connector_id
