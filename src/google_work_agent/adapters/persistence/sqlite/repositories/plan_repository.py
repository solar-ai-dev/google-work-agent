"""SQLite plan repository including corrective-plan draft reuse."""

import sqlite3

from google_work_agent.domain.plan.model import Plan as PlanRecord
from google_work_agent.domain.plan.model import PlanReviewStatus, PlanStatusV1


class SQLitePlanRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    @staticmethod
    def _record(row: sqlite3.Row) -> PlanRecord:
        return PlanRecord(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            revision_no=int(row["revision_no"]),
            status=PlanStatusV1(str(row["status"])),
            summary_text=None if row["summary_text"] is None else str(row["summary_text"]),
            created_at_ms=int(row["created_at_ms"]),
            review_status=PlanReviewStatus(str(row["review_status"])),
            review_version=int(row["review_version"]),
            review_disposition=(
                None if row["review_disposition"] is None else str(row["review_disposition"])
            ),
        )

    def get_by_id(self, plan_id: str) -> PlanRecord | None:
        row = self._connection.execute(
            """SELECT id, run_id, revision_no, status, summary_text, created_at_ms,
                      review_status, review_version, review_disposition
               FROM plans WHERE id = ?;""",
            (plan_id,),
        ).fetchone()
        return None if row is None else self._record(row)

    def insert_draft(self, plan: PlanRecord) -> None:
        existing = self.get_by_id(plan.id)
        if existing is None:
            self._connection.execute(
                """INSERT INTO plans (
                       id, run_id, revision_no, status, summary_text, created_at_ms,
                       review_status, review_version, review_disposition
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);""",
                (
                    plan.id,
                    plan.run_id,
                    plan.revision_no,
                    plan.status.value,
                    plan.summary_text,
                    plan.created_at_ms,
                    plan.review_status.value,
                    plan.review_version,
                    plan.review_disposition,
                ),
            )
            return
        has_actions = (
            self._connection.execute(
                "SELECT 1 FROM actions WHERE plan_id = ? LIMIT 1;", (plan.id,)
            ).fetchone()
            is not None
        )
        if (
            existing.run_id != plan.run_id
            or existing.revision_no != plan.revision_no
            or existing.status is not PlanStatusV1.DRAFT
            or has_actions
        ):
            raise sqlite3.IntegrityError(
                "existing plan is not the exact empty reserved corrective draft"
            )
        self._connection.execute(
            "UPDATE plans SET summary_text = ? WHERE id = ? AND status = 'DRAFT';",
            (plan.summary_text, plan.id),
        )

    def update_if_status(
        self, plan_id: str, *, expected_status: PlanStatusV1, next_status: PlanStatusV1
    ) -> PlanRecord | None:
        cursor = self._connection.execute(
            "UPDATE plans SET status=? WHERE id=? AND status=?;",
            (next_status.value, plan_id, expected_status.value),
        )
        if cursor.rowcount != 1:
            return None
        return self.get_by_id(plan_id)

    def update_review_if_version_and_status(
        self,
        plan_id: str,
        *,
        expected_review_version: int,
        expected_review_statuses: frozenset[PlanReviewStatus],
        values: dict[str, object],
    ) -> PlanRecord | None:
        if not values or not expected_review_statuses:
            raise ValueError("Plan review CAS requires values and expected statuses")
        allowed_columns = {"review_status", "review_version", "review_disposition"}
        if not set(values).issubset(allowed_columns):
            raise ValueError("Plan review CAS contains an unsupported column")
        normalized = {
            key: value.value if isinstance(value, PlanReviewStatus) else value
            for key, value in values.items()
        }
        set_clause = ", ".join(f"{column}=?" for column in normalized)
        placeholders = ", ".join("?" for _ in expected_review_statuses)
        cursor = self._connection.execute(
            f"UPDATE plans SET {set_clause} WHERE id=? AND review_version=? "
            f"AND review_status IN ({placeholders});",
            [
                *normalized.values(),
                plan_id,
                expected_review_version,
                *(status.value for status in expected_review_statuses),
            ],
        )
        return None if cursor.rowcount != 1 else self.get_by_id(plan_id)

    def list_by_run(self, run_id: str) -> tuple[PlanRecord, ...]:
        rows = self._connection.execute(
            """SELECT id, run_id, revision_no, status, summary_text, created_at_ms,
                      review_status, review_version, review_disposition
               FROM plans WHERE run_id=? ORDER BY revision_no ASC;""",
            (run_id,),
        ).fetchall()
        return tuple(self._record(row) for row in rows)
