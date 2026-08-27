"""SQLite evidence repository."""

import sqlite3

from google_work_agent.domain.evidence.model import Evidence as EvidenceRecord
from google_work_agent.domain.evidence.model import EvidenceOriginType


class SqliteEvidenceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def insert_bounded(
        self, record: EvidenceRecord, *, action_ids: tuple[str, ...] = ()
    ) -> None:
        self._connection.execute(
            "INSERT INTO evidence (id, run_id, origin_type, resource_ref_id, message_id, kind, excerpt, locator_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);",  # noqa: E501
            (
                record.id,
                record.run_id,
                record.origin_type.value,
                record.resource_ref_id,
                record.message_id,
                record.kind,
                record.excerpt,
                record.locator_json,
                record.created_at_ms,
            ),
        )
        self._connection.executemany(
            "INSERT OR IGNORE INTO action_evidence (action_id, evidence_id) VALUES (?, ?);",
            ((action_id, record.id) for action_id in action_ids),
        )

    def list_for_run(self, run_id: str, *, limit: int = 500) -> tuple[EvidenceRecord, ...]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        rows = self._connection.execute(
            "SELECT id, run_id, origin_type, resource_ref_id, message_id, kind, excerpt, "
            "locator_json, created_at_ms FROM evidence WHERE run_id=? "
            "ORDER BY created_at_ms, id LIMIT ?;", (run_id, limit)
        ).fetchall()
        return tuple(self._record(row) for row in rows)

    def list_for_action(self, action_id: str) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute(
            "SELECT e.id, e.run_id, e.origin_type, e.resource_ref_id, e.message_id, e.kind, e.excerpt, e.locator_json, e.created_at_ms FROM evidence AS e JOIN action_evidence AS ae ON ae.evidence_id = e.id WHERE ae.action_id = ? ORDER BY e.created_at_ms ASC, e.id ASC;",  # noqa: E501
            (action_id,),
        ).fetchall()
        return tuple(self._record(r) for r in rows)

    @staticmethod
    def _record(r: sqlite3.Row) -> EvidenceRecord:
        return EvidenceRecord(
            id=str(r["id"]),
            run_id=str(r["run_id"]),
            origin_type=EvidenceOriginType(str(r["origin_type"])),
            resource_ref_id=None if r["resource_ref_id"] is None else str(r["resource_ref_id"]),
            message_id=None if r["message_id"] is None else str(r["message_id"]),
            kind=str(r["kind"]),
            excerpt=str(r["excerpt"]),
            locator_json=None if r["locator_json"] is None else str(r["locator_json"]),
            created_at_ms=int(r["created_at_ms"]),
        )
