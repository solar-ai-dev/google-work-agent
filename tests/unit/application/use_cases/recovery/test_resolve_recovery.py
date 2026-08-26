from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommand,
    ResolveRecoveryHandler,
)
from google_work_agent.domain.enums import RecoveryResolution


def test_recheck_from_recovery_required_transitions_to_verifying(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    result = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert result.applied
    assert result.current_status == "VERIFYING"
    assert _count(database_path, "command_receipts") == 1
    assert _count(database_path, "recovery_contexts") == 0
    assert _audit_events(database_path) == ["RECOVERY_RESOLVED"]


def test_replay_with_same_request_hash_returns_cached_result(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    first = handler(_command("cmd-1", RecoveryResolution.RECHECK))
    second = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert first == second
    assert _count(database_path, "command_receipts") == 1


def test_cancel_without_durable_intent_fails_closed_via_domain_guard(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    result = handler(_command("cmd-1", RecoveryResolution.CANCEL))

    assert result.applied is False
    assert result.result_code == "RESOLUTION_NOT_ALLOWED"
    assert _count(database_path, "command_receipts") == 1


def test_resolution_from_non_recovery_required_status_fails_closed_via_domain_guard(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    result = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert result.applied is False
    assert result.result_code == "STATE_CONFLICT"
    assert _count(database_path, "command_receipts") == 1


def _command(command_id: str, resolution: RecoveryResolution) -> ResolveRecoveryCommand:
    return ResolveRecoveryCommand(
        run_id="r-1",
        expected_version=0,
        command_id=command_id,
        request_hash="a" * 64,
        resolution=resolution,
        recheck_input_changed=True,
    )


def _count(database_path: Path, table: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()
    return int(row["n"])


def _audit_events(database_path: Path) -> list[str]:
    with connect_sqlite(database_path) as connection:
        rows = connection.execute("SELECT event_type FROM audit_events ORDER BY id;").fetchall()
    return [str(row["event_type"]) for row in rows]


def _database(tmp_path: Path, *, run_status: str) -> Path:
    path = tmp_path / "resolve-recovery.db"
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
        connection.execute(
            """
            INSERT INTO recovery_contexts (
                run_id, reason, scope, action_id, pre_recovery_status,
                recovery_fingerprint, version, created_at_ms, updated_at_ms
            ) VALUES ('r-1', 'VERIFICATION_MISMATCH', 'RUN', NULL, 'WAITING_APPROVAL',
                      'test-fingerprint', 0, 1, 1);
            """
        )
        connection.commit()
    return path
