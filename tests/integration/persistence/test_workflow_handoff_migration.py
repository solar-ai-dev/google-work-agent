"""Forward-migration contract for the durable workflow handoff outbox."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite

MIGRATIONS = Path("src/google_work_agent/adapters/persistence/migrations")


def test_0008_database_upgrades_to_0009_without_changing_applied_receipts(
    tmp_path: Path,
) -> None:
    first_eight = tmp_path / "first-eight"
    first_eight.mkdir()
    for path in sorted(MIGRATIONS.glob("*.sql"))[:8]:
        (first_eight / path.name).write_bytes(path.read_bytes())
    connection = connect_sqlite(tmp_path / "upgrade.db")
    try:
        apply_migrations(connection, migrations_dir=first_eight, now_ms=lambda: 1)
        before = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version;"
        ).fetchall()

        results = apply_migrations(connection, now_ms=lambda: 2)
        after = connection.execute(
            "SELECT version, name, checksum FROM schema_migrations ORDER BY version;"
        ).fetchall()

        assert [result.applied for result in results] == [False] * 8 + [True]
        assert [tuple(row) for row in after[:8]] == [tuple(row) for row in before]
        assert tuple(after[8])[:2] == (9, "workflow_handoff_outbox")
    finally:
        connection.close()


def test_0009_creates_lookup_indexes_and_fails_closed_on_invalid_rows(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "constraints.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        indexes = {
            str(row["name"])
            for row in connection.execute("PRAGMA index_list('workflow_handoffs');").fetchall()
        }
        assert {
            "ix_workflow_handoffs_dispatch_head",
            "ix_workflow_handoffs_redrive",
            "ix_workflow_handoffs_blocked_binding",
        } <= indexes

        _seed_run(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_handoff(connection, execution_kind="START", checkpoint_id="cp-1")
        with pytest.raises(sqlite3.IntegrityError):
            _insert_handoff(
                connection,
                execution_kind="RESUME",
                checkpoint_id=None,
                checkpoint_generation=0,
            )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_handoff(
                connection,
                control_kind="CONFIRMATION_RESPONSE",
                control_payload_json=None,
                control_payload_hash="a" * 64,
            )
    finally:
        connection.close()


def _seed_run(connection: sqlite3.Connection) -> None:
    connection.execute(
        "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
    )
    connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
    connection.execute(
        """
        INSERT INTO runs (
            id, conversation_id, entry_mode, status, langgraph_thread_id,
            requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
        ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-1',
                  'AUTO', NULL, '{}', 0, 1, NULL);
        """
    )


def _insert_handoff(
    connection: sqlite3.Connection,
    *,
    execution_kind: str = "START",
    checkpoint_id: str | None = None,
    checkpoint_generation: int = 0,
    control_kind: str = "NONE",
    control_payload_json: str | None = None,
    control_payload_hash: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO workflow_handoffs (
            handoff_id, trigger_command_id, run_id, langgraph_thread_id,
            graph_profile, graph_version, requested_mode, execution_kind,
            resume_target_json, checkpoint_id, checkpoint_generation, run_sequence,
            control_kind, control_payload_json, control_payload_hash, status,
            created_at_ms, version
        ) VALUES ('h-1', 'cmd-1', 'r-1', 't-1', 'SIX_ROLE_BASELINE', 'v1',
                  'AUTO', ?, NULL, ?, ?, 1, ?, ?, ?, 'PENDING', 1, 0);
        """,
        (
            execution_kind,
            checkpoint_id,
            checkpoint_generation,
            control_kind,
            control_payload_json,
            control_payload_hash,
        ),
    )
