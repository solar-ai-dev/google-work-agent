"""SQLite evidence repository."""
import sqlite3
from google_work_agent.ports.models import EvidenceOriginType, EvidenceRecord

class SQLiteEvidenceRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection = connection
    def insert(self, record: EvidenceRecord) -> None:
        self._connection.execute("INSERT INTO evidence (id, run_id, origin_type, resource_ref_id, message_id, kind, excerpt, locator_json, created_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);", (record.id, record.run_id, record.origin_type.value, record.resource_ref_id, record.message_id, record.kind, record.excerpt, record.locator_json, record.created_at_ms))
    def link_to_action(self, *, action_id: str, evidence_id: str) -> None:
        self._connection.execute("INSERT OR IGNORE INTO action_evidence (action_id, evidence_id) VALUES (?, ?);", (action_id, evidence_id))
    def list_by_action(self, action_id: str) -> tuple[EvidenceRecord, ...]:
        rows = self._connection.execute("SELECT e.id, e.run_id, e.origin_type, e.resource_ref_id, e.message_id, e.kind, e.excerpt, e.locator_json, e.created_at_ms FROM evidence AS e JOIN action_evidence AS ae ON ae.evidence_id = e.id WHERE ae.action_id = ? ORDER BY e.created_at_ms ASC, e.id ASC;", (action_id,)).fetchall()
        return tuple(EvidenceRecord(id=str(r["id"]), run_id=str(r["run_id"]), origin_type=EvidenceOriginType(str(r["origin_type"])), resource_ref_id=None if r["resource_ref_id"] is None else str(r["resource_ref_id"]), message_id=None if r["message_id"] is None else str(r["message_id"]), kind=str(r["kind"]), excerpt=str(r["excerpt"]), locator_json=None if r["locator_json"] is None else str(r["locator_json"]), created_at_ms=int(r["created_at_ms"])) for r in rows)
