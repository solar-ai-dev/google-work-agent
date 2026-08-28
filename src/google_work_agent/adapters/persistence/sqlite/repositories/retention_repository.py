"""SQLite child-first bounded retention implementation."""

import sqlite3

from google_work_agent.ports.persistence.retention_repository import (
    RetentionCutoffs,
    RetentionPurgeResult,
)

_TERMINAL_RUN_STATUSES = ("COMPLETED", "CANCELLED", "FAILED", "BLOCKED")


class SqliteRetentionRepository:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def purge_batch(self, cutoffs: RetentionCutoffs, batch_limit: int) -> RetentionPurgeResult:
        if not 1 <= batch_limit <= 500:
            raise ValueError("batch_limit must be between 1 and 500")
        statuses = ",".join("?" for _ in _TERMINAL_RUN_STATUSES)
        rows = self._connection.execute(
            f"""SELECT r.id FROM runs AS r
                WHERE r.status IN ({statuses}) AND r.finished_at_ms IS NOT NULL
                  AND r.finished_at_ms < ?
                  AND NOT EXISTS (SELECT 1 FROM recovery_contexts c WHERE c.run_id=r.id)
                ORDER BY r.finished_at_ms, r.id LIMIT ?;""",
            (*_TERMINAL_RUN_STATUSES, cutoffs.terminal_run_ms, batch_limit),
        ).fetchall()
        run_ids = tuple(str(row["id"]) for row in rows)
        checkpoints = 0
        receipts = 0
        traces = 0
        if run_ids:
            marks = ",".join("?" for _ in run_ids)
            traces = int(
                self._connection.execute(
                    f"SELECT COUNT(*) AS count FROM trace_events WHERE run_id IN ({marks});",
                    run_ids,
                ).fetchone()["count"]
            )
            if self._table_exists("workflow_checkpoint_envelopes") and self._table_exists(
                "checkpoints"
            ):
                checkpoint_rows = self._connection.execute(
                    f"""SELECT langgraph_thread_id, checkpoint_ns, checkpoint_id
                        FROM workflow_checkpoint_envelopes
                        WHERE run_id IN ({marks});""",
                    run_ids,
                ).fetchall()
                for row in checkpoint_rows:
                    checkpoints += self._connection.execute(
                        """DELETE FROM checkpoints
                           WHERE thread_id=? AND checkpoint_ns=? AND checkpoint_id=?;""",
                        tuple(row),
                    ).rowcount
            receipt_cursor = self._connection.execute(
                f"""DELETE FROM command_receipts
                    WHERE (aggregate_type='Run' AND aggregate_id IN ({marks}))
                       OR (aggregate_type='Plan' AND aggregate_id IN (
                             SELECT id FROM plans WHERE run_id IN ({marks})
                          ))
                       OR (aggregate_type='Action' AND aggregate_id IN (
                             SELECT a.id FROM actions a JOIN plans p ON p.id=a.plan_id
                             WHERE p.run_id IN ({marks})
                          ))
                       OR (aggregate_type='Approval' AND aggregate_id IN (
                             SELECT ap.id FROM approvals ap
                             JOIN actions a ON a.id=ap.action_id
                             JOIN plans p ON p.id=a.plan_id
                             WHERE p.run_id IN ({marks})
                          ))
                       OR (aggregate_type='ExecutionAttempt' AND aggregate_id IN (
                             SELECT ea.id FROM execution_attempts ea
                             JOIN approvals ap ON ap.id=ea.approval_id
                             JOIN actions a ON a.id=ap.action_id
                             JOIN plans p ON p.id=a.plan_id
                             WHERE p.run_id IN ({marks})
                          ));""",
                run_ids * 5,
            )
            receipts += receipt_cursor.rowcount
            self._connection.execute(
                f"DELETE FROM workflow_handoffs WHERE run_id IN ({marks});", run_ids
            )
            self._connection.execute(f"DELETE FROM runs WHERE id IN ({marks});", run_ids)
        messages = self._delete_bounded(
            "messages", "created_at_ms < ? AND run_id IS NULL", cutoffs.message_ms, batch_limit
        )
        conversation_rows = self._connection.execute(
            """SELECT id FROM conversations
               WHERE updated_at_ms < ?
                 AND NOT EXISTS (
                     SELECT 1 FROM runs WHERE conversation_id=conversations.id
                 )
                 AND NOT EXISTS (
                     SELECT 1 FROM messages WHERE conversation_id=conversations.id
                 )
               ORDER BY updated_at_ms, id LIMIT ?;""",
            (cutoffs.conversation_ms, batch_limit),
        ).fetchall()
        conversation_ids = tuple(str(row["id"]) for row in conversation_rows)
        if conversation_ids:
            conversation_marks = ",".join("?" for _ in conversation_ids)
            receipts += self._connection.execute(
                f"DELETE FROM command_receipts WHERE aggregate_type='Conversation' "
                f"AND aggregate_id IN ({conversation_marks});",
                conversation_ids,
            ).rowcount
            conversations = self._connection.execute(
                f"DELETE FROM conversations WHERE id IN ({conversation_marks});",
                conversation_ids,
            ).rowcount
        else:
            conversations = 0
        audits = self._delete_bounded(
            "audit_events", "created_at_ms < ?", cutoffs.audit_ms, batch_limit
        )
        return RetentionPurgeResult(
            runs=len(run_ids),
            checkpoints=checkpoints,
            receipts=receipts,
            messages=messages,
            conversations=conversations,
            traces=traces,
            audits=audits,
        )

    def _delete_bounded(self, table: str, predicate: str, cutoff_ms: int, limit: int) -> int:
        cursor = self._connection.execute(
            f"DELETE FROM {table} WHERE rowid IN (SELECT rowid FROM {table} "
            f"WHERE {predicate} ORDER BY rowid LIMIT ?);",
            (cutoff_ms, limit),
        )
        return cursor.rowcount

    def _table_exists(self, table: str) -> bool:
        return (
            self._connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;", (table,)
            ).fetchone()
            is not None
        )
