from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.retention_repository import (
    SqliteRetentionRepository,
)
from google_work_agent.ports.persistence.retention_repository import RetentionCutoffs


def _seed_retention_database(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL)"
        )
        for suffix in ("terminal-1", "terminal-2", "open"):
            connection.execute(
                "INSERT INTO conversations VALUES (?, 'account-1', ?, 1, 1)",
                (f"conversation-{suffix}", suffix),
            )
        for suffix in ("terminal-1", "terminal-2"):
            connection.execute(
                """INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, budget_json, version, started_at_ms, finished_at_ms
                ) VALUES (?, ?, 'AGENT_SEARCH', 'COMPLETED', ?, 'AUTO', '{}', 1, 1, 10)""",
                (f"run-{suffix}", f"conversation-{suffix}", f"thread-{suffix}"),
            )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES (
                'run-open', 'conversation-open', 'AGENT_SEARCH', 'ANALYZING',
                'thread-open', 'AUTO', '{}', 0, 1
            )"""
        )
        for suffix in ("terminal-1", "terminal-2", "open"):
            connection.execute(
                """INSERT INTO messages
                    (id, conversation_id, run_id, role, content, created_at_ms)
                    VALUES (?, ?, ?, 'USER', 'message', 1)""",
                (
                    f"message-{suffix}",
                    f"conversation-{suffix}",
                    f"run-{suffix}",
                ),
            )
            connection.execute(
                """INSERT INTO trace_events
                    (run_id, event_type, payload_json, created_at_ms)
                    VALUES (?, 'TRACE', '{}', 1)""",
                (f"run-{suffix}",),
            )
            connection.execute(
                """INSERT INTO command_receipts (
                    command_id, command_type, request_hash, aggregate_type,
                    aggregate_id, status, result_code, result_version,
                    response_json, created_at_ms, completed_at_ms
                ) VALUES (?, 'Test', ?, 'Run', ?, 'APPLIED',
                          'TRANSITION_APPLIED', 1, '{}', 1, 2)""",
                (f"receipt-{suffix}", suffix[0] * 64, f"run-{suffix}"),
            )
        for created_at_ms in (1, 2, 1_000):
            connection.execute(
                """INSERT INTO audit_events (
                    actor_type, actor_id, event_type, outcome, metadata_json,
                    created_at_ms
                ) VALUES ('SYSTEM', 'test', 'AUDIT', 'OK', '{}', ?)""",
                (created_at_ms,),
            )
    finally:
        connection.close()


def test_retention_is_bounded__child_first_and__preserves_open_run_replay(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "retention.db"
    _seed_retention_database(database_path)
    connection = connect_sqlite(database_path)
    try:
        repository = SqliteRetentionRepository(connection)
        cutoffs = RetentionCutoffs(
            terminal_run_ms=100,
            message_ms=100,
            conversation_ms=100,
            trace_ms=100,
            audit_ms=100,
        )

        first = repository.purge_batch(cutoffs, 1)
        assert first.runs == 1
        assert first.traces == 1
        assert first.receipts == 1
        assert first.messages == 1
        assert first.conversations == 1
        assert first.audits == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM runs WHERE status='COMPLETED'").fetchone()[0]
            == 1
        )

        repository.purge_batch(cutoffs, 1)
        assert (
            connection.execute("SELECT COUNT(*) FROM runs WHERE status='COMPLETED'").fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT status FROM runs WHERE id='run-open'").fetchone()[0]
            == "ANALYZING"
        )
        assert (
            connection.execute(
                "SELECT status FROM command_receipts WHERE command_id='receipt-open'"
            ).fetchone()[0]
            == "APPLIED"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM trace_events WHERE run_id='run-open'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE created_at_ms=1000"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()
