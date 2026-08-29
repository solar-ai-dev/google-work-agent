"""SQLite Run persistence/query/CAS adapter."""

import sqlite3

from google_work_agent.domain.run.model import (
    Run,
    RunCreate,
    RunStatusV1,
    TerminalResultKindV1,
)
from google_work_agent.ports.persistence.run_repository import RunAlreadyOpenConflictError


class SqliteRunRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, run_id: str) -> Run | None:
        row = self._connection.execute(
            "SELECT id, conversation_id, entry_mode, status, langgraph_thread_id, "
            "requested_mode, actual_runtime, version, started_at_ms, finished_at_ms, "
            "terminal_result_kind "
            "FROM runs WHERE id=?;",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return Run(
            id=str(row["id"]),
            conversation_id=str(row["conversation_id"]),
            status=RunStatusV1(str(row["status"])),
            version=int(row["version"]),
            started_at_ms=int(row["started_at_ms"]),
            finished_at_ms=(None if row["finished_at_ms"] is None else int(row["finished_at_ms"])),
            entry_mode=str(row["entry_mode"]),
            langgraph_thread_id=str(row["langgraph_thread_id"]),
            requested_mode=str(row["requested_mode"]),
            actual_runtime=(None if row["actual_runtime"] is None else str(row["actual_runtime"])),
            terminal_result_kind=(
                None
                if row["terminal_result_kind"] is None
                else TerminalResultKindV1(str(row["terminal_result_kind"]))
            ),
        )

    def get_snapshot(self, run_id: str) -> Run | None:
        return self.get(run_id)

    def find_open_by_conversation(self, conversation_id: str) -> Run | None:
        row = self._connection.execute(
            "SELECT id FROM runs WHERE conversation_id=? AND finished_at_ms IS NULL "
            "ORDER BY started_at_ms DESC LIMIT 1;",
            (conversation_id,),
        ).fetchone()
        return None if row is None else self.get(str(row["id"]))

    def list_for_conversation_bounded(
        self, conversation_id: str, *, limit: int
    ) -> tuple[Run, ...]:
        if limit < 1:
            raise ValueError("run limit must be positive")
        rows = self._connection.execute(
            """
            SELECT id
            FROM runs
            WHERE conversation_id = ?
            ORDER BY started_at_ms DESC, id DESC
            LIMIT ?;
            """,
            (conversation_id, limit),
        ).fetchall()
        return tuple(
            run
            for row in reversed(rows)
            if (run := self.get(str(row["id"]))) is not None
        )

    def create(self, run: RunCreate) -> None:
        try:
            self._connection.execute(
                "INSERT INTO runs (id, conversation_id, entry_mode, status, "
                "langgraph_thread_id, requested_mode, actual_runtime, budget_json, "
                "version, started_at_ms, finished_at_ms, terminal_result_kind) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);",
                (
                    run.id,
                    run.conversation_id,
                    run.entry_mode,
                    run.status.value,
                    run.langgraph_thread_id,
                    run.requested_mode,
                    run.actual_runtime,
                    run.budget_json,
                    run.version,
                    run.started_at_ms,
                    run.finished_at_ms,
                    None if run.terminal_result_kind is None else run.terminal_result_kind.value,
                ),
            )
        except sqlite3.IntegrityError as error:
            if self.find_open_by_conversation(run.conversation_id) is not None:
                raise RunAlreadyOpenConflictError("conversation already has an open run") from error
            raise

    def update_if_version_and_status(
        self,
        run_id: str,
        expected_version: int,
        expected_statuses: frozenset[RunStatusV1],
        values: dict[str, object],
    ) -> bool:
        if not values or not expected_statuses:
            raise ValueError("Run CAS requires values and expected statuses")
        allowed_columns = {
            "status",
            "version",
            "finished_at_ms",
            "actual_runtime",
            "terminal_result_kind",
        }
        if not set(values).issubset(allowed_columns):
            raise ValueError("Run CAS contains an unsupported column")
        set_clause = ", ".join(f"{column} = ?" for column in values)
        placeholders = ", ".join("?" for _ in expected_statuses)
        cursor = self._connection.execute(
            f"UPDATE runs SET {set_clause} WHERE id=? AND version=? "
            f"AND status IN ({placeholders});",
            [
                *values.values(),
                run_id,
                expected_version,
                *(status.value for status in expected_statuses),
            ],
        )
        return cursor.rowcount == 1
