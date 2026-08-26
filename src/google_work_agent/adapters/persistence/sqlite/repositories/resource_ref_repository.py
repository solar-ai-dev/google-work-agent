"""SQLite realization of canonical connector-bound ResourceRef persistence."""

from __future__ import annotations

import sqlite3

from google_work_agent.ports.models import ResourceRefRecord, ResourceSource


class SqliteResourceRefRepository:
    _SELECT = """
        SELECT id, run_id, connector_id, source, resource_type, resource_id,
               parent_resource_id, canonical_url, title, event_time_ms,
               version_token, metadata_json, captured_at_ms
        FROM resource_refs
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def upsert_bound_ref(self, record: ResourceRefRecord) -> ResourceRefRecord:
        if not record.connector_id:
            raise ValueError("resource reference persistence requires connector_id")
        self._connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, source, resource_type, resource_id,
                parent_resource_id, canonical_url, title, event_time_ms,
                version_token, metadata_json, captured_at_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, connector_id, resource_type, resource_id)
            DO UPDATE SET
                source = excluded.source,
                parent_resource_id = excluded.parent_resource_id,
                canonical_url = excluded.canonical_url,
                title = excluded.title,
                event_time_ms = excluded.event_time_ms,
                version_token = excluded.version_token,
                metadata_json = excluded.metadata_json,
                captured_at_ms = excluded.captured_at_ms;
            """,
            (
                record.id,
                record.run_id,
                record.connector_id,
                record.source.value,
                record.resource_type,
                record.resource_id,
                record.parent_resource_id,
                record.canonical_url,
                record.title,
                record.event_time_ms,
                record.version_token,
                record.metadata_json,
                record.captured_at_ms,
            ),
        )
        row = self._connection.execute(
            self._SELECT
            + " WHERE run_id = ? AND connector_id = ? AND resource_type = ? AND resource_id = ?;",
            (record.run_id, record.connector_id, record.resource_type, record.resource_id),
        ).fetchone()
        if row is None:
            raise sqlite3.IntegrityError("upserted ResourceRef is not readable")
        return self._record(row)

    def get(self, resource_ref_id: str) -> ResourceRefRecord | None:
        row = self._connection.execute(
            self._SELECT + " WHERE id = ?;", (resource_ref_id,)
        ).fetchone()
        return None if row is None else self._record(row)

    def list_for_run_bounded(self, run_id: str, *, limit: int) -> tuple[ResourceRefRecord, ...]:
        if limit < 1 or limit > 1000:
            raise ValueError("ResourceRef list limit must be between 1 and 1000")
        rows = self._connection.execute(
            self._SELECT
            + """
              WHERE run_id = ?
              ORDER BY connector_id, source, resource_type, resource_id LIMIT ?;
              """,
            (run_id, limit),
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    @staticmethod
    def _record(row: sqlite3.Row) -> ResourceRefRecord:
        return ResourceRefRecord(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            connector_id=str(row["connector_id"]),
            source=ResourceSource(str(row["source"])),
            resource_type=str(row["resource_type"]),
            resource_id=str(row["resource_id"]),
            parent_resource_id=(
                None if row["parent_resource_id"] is None else str(row["parent_resource_id"])
            ),
            canonical_url=None if row["canonical_url"] is None else str(row["canonical_url"]),
            title=None if row["title"] is None else str(row["title"]),
            event_time_ms=None if row["event_time_ms"] is None else int(row["event_time_ms"]),
            version_token=None if row["version_token"] is None else str(row["version_token"]),
            metadata_json=str(row["metadata_json"]),
            captured_at_ms=int(row["captured_at_ms"]),
        )
