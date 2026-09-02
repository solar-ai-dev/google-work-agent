from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.retention_repository import (
    SqliteRetentionRepository,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.ports.persistence.recovery_repository import (
    RecoveryConflictError,
    RecoveryContextV1,
)
from google_work_agent.ports.persistence.retention_repository import RetentionCutoffs
from google_work_agent.ports.system.contracts.workflow_handoff import MainControlResumeTargetV2


def test_store_context__then_load__current_round_trips(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        stored = unit_of_work.recovery_contexts.store_context(_context())
        unit_of_work.commit()
    with factory() as unit_of_work:
        loaded = unit_of_work.recovery_contexts.load_current_context("r-1")

    assert stored == loaded
    assert loaded is not None
    assert loaded["reason"] == "CHECKPOINT_MISMATCH"
    assert loaded["scope"] == "RUN"
    assert loaded["pre_recovery_status"] == "ANALYZING"
    assert loaded["registered_resume_target"] is not None
    assert "action_id" not in loaded


def test_store_context__rejects_stale__version(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context())
        unit_of_work.commit()

    with factory() as unit_of_work, pytest.raises(RecoveryConflictError):
        unit_of_work.recovery_contexts.store_context(_context())  # version=0 again -> conflict
        unit_of_work.commit()


def test_store_context__accepts_version__bump(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context())
        unit_of_work.commit()
    with factory() as unit_of_work:
        updated = unit_of_work.recovery_contexts.store_context(
            _context(version=1, recovery_fingerprint="fp-2")
        )
        unit_of_work.commit()

    assert updated["version"] == 1
    assert updated["recovery_fingerprint"] == "fp-2"


def test_database_rejects__foreign_reason__fingerprint(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    invalid = _context()
    invalid["observed_external_state_fingerprint"] = "mismatch-only"
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)

    with factory() as unit_of_work, pytest.raises(sqlite3.IntegrityError):
        unit_of_work.recovery_contexts.store_context(invalid)


def test_clear_context__removes_current__context(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context())
        unit_of_work.commit()
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.clear_context("r-1", expected_version=0)
        unit_of_work.commit()
    with factory() as unit_of_work:
        loaded = unit_of_work.recovery_contexts.load_current_context("r-1")

    assert loaded is None


def test_clear_context__rejects_stale__expected_version(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context())
        unit_of_work.commit()

    with factory() as unit_of_work, pytest.raises(RecoveryConflictError):
        unit_of_work.recovery_contexts.clear_context("r-1", expected_version=5)
        unit_of_work.commit()


def test_clear_context__preserves_version__monotonicity_across_recreation(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context(version=0))
        unit_of_work.commit()
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.clear_context("r-1", expected_version=0)
        unit_of_work.commit()

    with factory() as unit_of_work, pytest.raises(RecoveryConflictError):
        unit_of_work.recovery_contexts.store_context(_context(version=0))

    with factory() as unit_of_work:
        recreated = unit_of_work.recovery_contexts.store_context(_context(version=1))
        unit_of_work.commit()

    assert recreated["version"] == 1


def test_cleared_context_tombstone__does_not_block__terminal_run_retention(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context(version=0))
        unit_of_work.commit()
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.clear_context("r-1", expected_version=0)
        unit_of_work.commit()

    connection = connect_sqlite(database_path)
    try:
        tombstone = connection.execute(
            "SELECT last_version FROM recovery_context_tombstones WHERE run_id='r-1';"
        ).fetchone()
        assert tombstone is not None and tombstone[0] == 0
        connection.execute(
            "UPDATE runs SET status='COMPLETED', terminal_result_kind='SUCCESS', "
            "finished_at_ms=20 WHERE id='r-1';"
        )
        result = SqliteRetentionRepository(connection).purge_batch(
            RetentionCutoffs(
                terminal_run_ms=100,
                message_ms=0,
                conversation_ms=0,
                trace_ms=0,
                audit_ms=0,
            ),
            10,
        )

        assert result.runs == 1
        assert connection.execute("SELECT COUNT(*) FROM runs WHERE id='r-1';").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM recovery_context_tombstones WHERE run_id='r-1';"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_active_recovery_context__still_protects_terminal__run_from_retention(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context(version=0))
        unit_of_work.commit()

    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "UPDATE runs SET status='COMPLETED', terminal_result_kind='SUCCESS', "
            "finished_at_ms=20 WHERE id='r-1';"
        )
        result = SqliteRetentionRepository(connection).purge_batch(
            RetentionCutoffs(
                terminal_run_ms=100,
                message_ms=0,
                conversation_ms=0,
                trace_ms=0,
                audit_ms=0,
            ),
            10,
        )

        assert result.runs == 0
        assert connection.execute("SELECT COUNT(*) FROM runs WHERE id='r-1';").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM recovery_contexts WHERE run_id='r-1';"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_list_candidates__bounded_orders__by_created_at(tmp_path: Path) -> None:
    database_path = _database(tmp_path, extra_runs=["r-2"])
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.recovery_contexts.store_context(_context(run_id="r-2", created_at_ms=5))
        unit_of_work.recovery_contexts.store_context(_context(run_id="r-1", created_at_ms=1))
        unit_of_work.commit()

    with factory() as unit_of_work:
        candidates = unit_of_work.recovery_contexts.list_candidates_bounded(10)

    assert [item["run_id"] for item in candidates] == ["r-1", "r-2"]


@pytest.mark.parametrize("limit", [0, -1, 1001])
def test_list_candidates__rejects_non_positive__or_unbounded_limit(
    tmp_path: Path, limit: int
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)

    with factory() as unit_of_work, pytest.raises(ValueError):
        unit_of_work.recovery_contexts.list_candidates_bounded(limit)


def _database(tmp_path: Path, *, extra_runs: list[str] | None = None) -> Path:
    path = tmp_path / "recovery.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        for index, run_id in enumerate(["r-1", *(extra_runs or [])]):
            conversation_id = f"c-{index + 1}"
            connection.execute(
                "INSERT INTO conversations VALUES (?, 'a-1', 'Test', 1, 1);",
                (conversation_id,),
            )
            connection.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, actual_runtime, budget_json, version, started_at_ms,
                    finished_at_ms
                ) VALUES (?, ?, 'AGENT_SEARCH', 'ANALYZING', ?,
                          'AUTO', NULL, '{}', 0, 1, NULL);
                """,
                (run_id, conversation_id, f"t-{run_id}"),
            )
        connection.commit()
    return path


def _context(
    *,
    run_id: str = "r-1",
    version: int = 0,
    recovery_fingerprint: str = "fp-1",
    created_at_ms: int = 10,
) -> RecoveryContextV1:
    return {
        "schema_version": 1,
        "run_id": run_id,
        "reason": "CHECKPOINT_MISMATCH",
        "scope": "RUN",
        "pre_recovery_status": "ANALYZING",
        "recovery_fingerprint": recovery_fingerprint,
        "registered_resume_target": MainControlResumeTargetV2(
            kind="MAIN_CONTROL",
            stage_id="PREFLIGHT",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
        ),
        "contract_or_checkpoint_fingerprint": "cp-fp-1",
        "version": version,
        "created_at_ms": created_at_ms,
        "updated_at_ms": created_at_ms,
    }
