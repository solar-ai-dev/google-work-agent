"""SQLite execution-attempt repository."""
import sqlite3
from google_work_agent.domain import ExecutionAttemptStatus
from google_work_agent.ports.models import ExecutionAttemptRecord

class SQLiteExecutionAttemptRepository:
    _SELECT="SELECT id, approval_id, attempt_no, status, version, result_resource_ref_id, response_metadata_json, error_code, error_detail_json, started_at_ms, finished_at_ms FROM execution_attempts"
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection=connection
    @staticmethod
    def _record(r: sqlite3.Row) -> ExecutionAttemptRecord:
        return ExecutionAttemptRecord(id=str(r["id"]), approval_id=str(r["approval_id"]), attempt_no=int(r["attempt_no"]), status=ExecutionAttemptStatus(str(r["status"])), version=int(r["version"]), result_resource_ref_id=None if r["result_resource_ref_id"] is None else str(r["result_resource_ref_id"]), response_metadata_json=None if r["response_metadata_json"] is None else str(r["response_metadata_json"]), error_code=None if r["error_code"] is None else str(r["error_code"]), error_detail_json=None if r["error_detail_json"] is None else str(r["error_detail_json"]), started_at_ms=int(r["started_at_ms"]), finished_at_ms=None if r["finished_at_ms"] is None else int(r["finished_at_ms"]))
    def get_by_id(self, attempt_id: str) -> ExecutionAttemptRecord | None:
        r=self._connection.execute(self._SELECT+" WHERE id=?;", (attempt_id,)).fetchone(); return None if r is None else self._record(r)
    def get_active_by_approval(self, approval_id: str) -> ExecutionAttemptRecord | None:
        r=self._connection.execute(self._SELECT+" WHERE approval_id=? AND status IN ('CLAIMED','EXECUTING','UNKNOWN_RESULT') ORDER BY attempt_no DESC LIMIT 1;", (approval_id,)).fetchone(); return None if r is None else self._record(r)
    def insert_claimed(self, record: ExecutionAttemptRecord) -> None:
        self._connection.execute("INSERT INTO execution_attempts (id, approval_id, attempt_no, status, version, result_resource_ref_id, response_metadata_json, error_code, error_detail_json, started_at_ms, finished_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", (record.id,record.approval_id,record.attempt_no,record.status.value,record.version,record.result_resource_ref_id,record.response_metadata_json,record.error_code,record.error_detail_json,record.started_at_ms,record.finished_at_ms))
    def update_status(self, attempt_id: str, *, expected_version: int, status: ExecutionAttemptStatus, error_code: str | None, error_detail_json: str | None, result_resource_ref_id: str | None, response_metadata_json: str | None, finished_at_ms: int | None) -> ExecutionAttemptRecord:
        current=self.get_by_id(attempt_id)
        if current is None: raise LookupError(f"execution attempt not found: {attempt_id}")
        if current.version != expected_version: raise sqlite3.IntegrityError("execution attempt version conflict")
        c=self._connection.execute("UPDATE execution_attempts SET status=?, version=version+1, result_resource_ref_id=?, response_metadata_json=?, error_code=?, error_detail_json=?, finished_at_ms=? WHERE id=? AND version=?;", (status.value,result_resource_ref_id,response_metadata_json,error_code,error_detail_json,finished_at_ms,attempt_id,expected_version))
        if c.rowcount != 1: raise sqlite3.IntegrityError("execution attempt update affected an unexpected row count")
        updated=self.get_by_id(attempt_id)
        if updated is None: raise LookupError(f"execution attempt not found after update: {attempt_id}")
        return updated
    def mark_succeeded(self, attempt_id: str, *, expected_version: int, result_resource_ref_id: str | None, response_metadata_json: str | None, finished_at_ms: int) -> ExecutionAttemptRecord:
        return self.update_status(attempt_id, expected_version=expected_version, status=ExecutionAttemptStatus.SUCCEEDED, error_code=None, error_detail_json=None, result_resource_ref_id=result_resource_ref_id, response_metadata_json=response_metadata_json, finished_at_ms=finished_at_ms)
    def mark_failed(self, attempt_id: str, *, expected_version: int, error_code: str, error_detail_json: str, finished_at_ms: int) -> ExecutionAttemptRecord:
        return self.update_status(attempt_id, expected_version=expected_version, status=ExecutionAttemptStatus.FAILED, error_code=error_code, error_detail_json=error_detail_json, result_resource_ref_id=None, response_metadata_json=None, finished_at_ms=finished_at_ms)
    def mark_unknown_result(self, attempt_id: str, *, expected_version: int, error_code: str, error_detail_json: str, finished_at_ms: int) -> ExecutionAttemptRecord:
        return self.update_status(attempt_id, expected_version=expected_version, status=ExecutionAttemptStatus.UNKNOWN_RESULT, error_code=error_code, error_detail_json=error_detail_json, result_resource_ref_id=None, response_metadata_json=None, finished_at_ms=finished_at_ms)
    def list_by_approval(self, approval_id: str) -> tuple[ExecutionAttemptRecord, ...]:
        return tuple(self._record(r) for r in self._connection.execute(self._SELECT+" WHERE approval_id=? ORDER BY attempt_no ASC;", (approval_id,)).fetchall())
