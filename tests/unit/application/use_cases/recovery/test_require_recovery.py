from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash


def test_first_call_atomically_persists_run_transition_context_and_audit(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    handler = RequireRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    result = handler(_command("cmd-1", "fp-1"))

    assert result.applied
    assert result.current_status == "RECOVERY_REQUIRED"
    assert _count(database_path, "recovery_contexts") == 1
    assert _count(database_path, "command_receipts") == 1
    with connect_sqlite(database_path) as connection:
        audits = connection.execute(
            "SELECT event_type, outcome FROM audit_events WHERE run_id = 'r-1';"
        ).fetchall()
    assert [dict(row) for row in audits] == [
        {"event_type": "RECOVERY_REQUIRED", "outcome": result.result_code}
    ]


def test_replay_with_same_request_hash_returns_cached_result_without_remutating(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    handler = RequireRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    first = handler(_command("cmd-1", "fp-1"))
    second = handler(_command("cmd-1", "fp-1"))

    assert first == second
    assert _count(database_path, "recovery_contexts") == 1
    assert _count(database_path, "command_receipts") == 1


def test_replay_with_different_request_hash_is_rejected_as_duplicate(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    handler = RequireRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    handler(_command("cmd-1", "fp-1"))
    conflicting = handler(
        RequireRecoveryCommand(
            run_id="r-1",
            expected_version=0,
            command_id="cmd-1",
            request_hash=calculate_canonical_json_hash({"command_id": "cmd-1", "round": 2}),
            reason="CHECKPOINT_MISMATCH",
            scope="RUN",
            recovery_fingerprint="fp-2",
        )
    )

    assert not conflicting.applied
    assert conflicting.result_code == "DUPLICATE_COMMAND"
    assert _count(database_path, "recovery_contexts") == 1


def test_terminal_run_is_not_applied_and_writes_no_context_or_audit(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="COMPLETED")
    handler = RequireRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    result = handler(_command("cmd-1", "fp-1"))

    assert not result.applied
    assert _count(database_path, "recovery_contexts") == 0
    assert _count(database_path, "command_receipts") == 1
    with connect_sqlite(database_path) as connection:
        audits = connection.execute(
            "SELECT COUNT(*) AS n FROM audit_events WHERE run_id = 'r-1';"
        ).fetchone()
    assert int(audits["n"]) == 0


def test_second_independent_recovery_declaration_bumps_context_version(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    handler = RequireRecoveryHandler(unit_of_work_factory=factory, now_ms=lambda: 10)
    handler(_command("cmd-1", "fp-1"))
    with connect_sqlite(database_path) as connection:
        connection.execute("UPDATE runs SET status = 'ANALYZING' WHERE id = 'r-1';")
        connection.commit()

    handler(
        RequireRecoveryCommand(
            run_id="r-1",
            expected_version=1,
            command_id="cmd-2",
            request_hash=calculate_canonical_json_hash({"round": 2}),
            reason="CONTRACT_VIOLATION",
            scope="RUN",
            recovery_fingerprint="fp-2",
        )
    )

    with factory() as unit_of_work:
        context = unit_of_work.recovery_contexts.load_current_context("r-1")
    assert context is not None
    assert context["version"] == 1
    assert context["reason"] == "CONTRACT_VIOLATION"


def _command(command_id: str, recovery_fingerprint: str) -> RequireRecoveryCommand:
    return RequireRecoveryCommand(
        run_id="r-1",
        expected_version=0,
        command_id=command_id,
        request_hash=calculate_canonical_json_hash({"command_id": command_id}),
        reason="CHECKPOINT_MISMATCH",
        scope="RUN",
        recovery_fingerprint=recovery_fingerprint,
    )


def _count(database_path: Path, table: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()
    return int(row["n"])


def _database(tmp_path: Path, *, run_status: str) -> Path:
    path = tmp_path / "require-recovery.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', ?, 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """,
            (run_status,),
        )
        connection.commit()
    return path
