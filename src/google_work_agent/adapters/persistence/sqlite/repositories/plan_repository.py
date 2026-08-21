"""SQLite plan repository including corrective-plan draft reuse."""
import sqlite3
from google_work_agent.ports.models import PlanRecord, PlanReviewStatus, PlanStatus

class SQLitePlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection=connection
    @staticmethod
    def _record(row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(id=str(row["id"]), run_id=str(row["run_id"]), revision_no=int(row["revision_no"]), status=PlanStatus(str(row["status"])), summary_text=None if row["summary_text"] is None else str(row["summary_text"]), created_at_ms=int(row["created_at_ms"]), review_status=PlanReviewStatus(str(row["review_status"])), review_version=int(row["review_version"]))
    def get_by_id(self, plan_id: str) -> PlanRecord | None:
        row=self._connection.execute("SELECT id, run_id, revision_no, status, summary_text, created_at_ms, review_status, review_version FROM plans WHERE id = ?;", (plan_id,)).fetchone(); return None if row is None else self._record(row)
    def insert_draft(self, plan: PlanRecord) -> None:
        existing=self.get_by_id(plan.id)
        if existing is None:
            self._connection.execute("INSERT INTO plans (id, run_id, revision_no, status, summary_text, created_at_ms, review_status, review_version) VALUES (?, ?, ?, ?, ?, ?, ?, ?);", (plan.id, plan.run_id, plan.revision_no, plan.status.value, plan.summary_text, plan.created_at_ms, plan.review_status.value, plan.review_version)); return
        has_actions=self._connection.execute("SELECT 1 FROM actions WHERE plan_id = ? LIMIT 1;", (plan.id,)).fetchone() is not None
        if existing.run_id != plan.run_id or existing.revision_no != plan.revision_no or existing.status is not PlanStatus.DRAFT or has_actions:
            raise sqlite3.IntegrityError("existing plan is not the exact empty reserved corrective draft")
        self._connection.execute("UPDATE plans SET summary_text = ? WHERE id = ? AND status = 'DRAFT';", (plan.summary_text, plan.id))
    def require_review(self, plan_id: str) -> int:
        c=self._connection.execute("UPDATE plans SET review_status='REQUIRED', review_version=review_version+1 WHERE id=? AND status IN ('WAITING_APPROVAL','ACTIVE');", (plan_id,))
        if c.rowcount != 1: raise sqlite3.IntegrityError("plan review invalidation affected an unexpected row count")
        return int(self._connection.execute("SELECT review_version FROM plans WHERE id=?;", (plan_id,)).fetchone()["review_version"])
    def store_review_result(self, plan_id: str, *, expected_review_version: int, review_status: str) -> bool:
        c=self._connection.execute("UPDATE plans SET review_status=? WHERE id=? AND review_version=? AND review_status <> 'PASSED';", (review_status, plan_id, expected_review_version))
        if c.rowcount > 1: raise sqlite3.IntegrityError("plan review result affected an unexpected row count")
        return c.rowcount == 1
    def _status(self, plan_id: str, sql: str, message: str) -> None:
        c=self._connection.execute(sql, (plan_id,))
        if c.rowcount != 1: raise sqlite3.IntegrityError(message)
    def activate(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='ACTIVE' WHERE id=? AND status='DRAFT';", "plan activation affected an unexpected row count")
    def wait_for_approval(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='WAITING_APPROVAL' WHERE id=? AND status='DRAFT';", "plan wait-for-approval affected an unexpected row count")
    def activate_waiting(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='ACTIVE' WHERE id=? AND status='WAITING_APPROVAL';", "waiting-approval plan activation affected an unexpected row count")
    def complete(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='COMPLETED' WHERE id=? AND status IN ('WAITING_APPROVAL','ACTIVE');", "plan completion affected an unexpected row count")
    def cancel(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='CANCELLED' WHERE id=? AND status IN ('WAITING_APPROVAL','ACTIVE');", "plan cancellation affected an unexpected row count")
    def supersede(self, plan_id: str) -> None: self._status(plan_id, "UPDATE plans SET status='SUPERSEDED' WHERE id=? AND status IN ('WAITING_APPROVAL','ACTIVE');", "plan supersede affected an unexpected row count")
    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        rows=self._connection.execute("SELECT id, run_id, revision_no, status, summary_text, created_at_ms, review_status, review_version FROM plans WHERE run_id=? ORDER BY revision_no ASC;", (run_id,)).fetchall(); return tuple(self._record(r) for r in rows)
