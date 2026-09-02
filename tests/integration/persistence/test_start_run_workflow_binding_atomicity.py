from __future__ import annotations

import itertools
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.start_run import StartRunCommand, StartRunHandler
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork

_TOOL_REGISTRY = load_signed_tool_registry()


def test_start_run_commits__one_binding_with__all_atomic_participants(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    handler = _handler(database_path)
    command = _command()

    first = handler(command)
    replay = handler(command)

    assert first.applied is True
    assert replay.request_replayed is True
    assert replay.enqueued is False
    with connect_sqlite(database_path) as connection:
        assert _count(connection, "runs") == 1
        assert _count(connection, "messages") == 1
        assert _count(connection, "workflow_bindings") == 1
        assert _count(connection, "workflow_handoffs") == 1
        assert _count(connection, "command_receipts") == 1
        assert _count(connection, "audit_events") == 1
        assert _count(connection, "trace_events") == 1
        binding = connection.execute(
            "SELECT * FROM workflow_bindings WHERE run_id=?", (first.run_id,)
        ).fetchone()
        handoff = connection.execute(
            "SELECT * FROM workflow_handoffs WHERE handoff_id=?", (first.handoff_id,)
        ).fetchone()
        assert binding is not None and handoff is not None
        assert binding["workflow_key"] == first.workflow_key
        assert binding["langgraph_thread_id"] == handoff["langgraph_thread_id"]


@pytest.mark.parametrize("failure_table", ["workflow_bindings", "workflow_handoffs"])
def test_binding_or_handoff__stage_failure_rolls__back_every_participant(
    tmp_path: Path, failure_table: str
) -> None:
    database_path = _database(tmp_path)
    _install_insert_failure(database_path, failure_table)

    with pytest.raises(sqlite3.IntegrityError):
        _handler(database_path)(_command())

    _assert_no_start_run_participant(database_path)


def test_commit_failure__leaves_no_partial__start_run_participant(tmp_path: Path) -> None:
    database_path = _database(tmp_path)

    def factory() -> UnitOfWork:
        return cast(UnitOfWork, _CommitFailingUnitOfWork(database_path))

    handler = StartRunHandler(
        unit_of_work_factory=factory,
        checkpoint_port=SqliteCheckpointAdapter(database_path, now_ms=lambda: 100),
        now_ms=lambda: 100,
        id_factory=_id_factory(),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        tool_registry=_TOOL_REGISTRY,
    )

    with pytest.raises(sqlite3.OperationalError, match="simulated commit failure"):
        handler(_command())

    _assert_no_start_run_participant(database_path)


class _CommitFailingUnitOfWork(SqliteUnitOfWork):
    def commit(self) -> None:
        self.rollback()
        raise sqlite3.OperationalError("simulated commit failure")


def _database(tmp_path: Path) -> Path:
    database_path = tmp_path / "start-run-atomic.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);"""
        )
        connection.execute(
            """INSERT INTO conversations (
                id, account_id, title, created_at_ms, updated_at_ms
            ) VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1);"""
        )
    checkpoint = SqliteCheckpointAdapter(database_path, now_ms=lambda: 1)
    checkpoint.close()
    return database_path


def _handler(database_path: Path) -> StartRunHandler:
    return StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=SqliteCheckpointAdapter(database_path, now_ms=lambda: 100),
        now_ms=lambda: 100,
        id_factory=_id_factory(),
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        tool_registry=_TOOL_REGISTRY,
    )


def _command() -> StartRunCommand:
    return StartRunCommand(
        command_id="command-1",
        request_hash="a" * 64,
        conversation_id="conversation-1",
        request_text="hello",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        api_contract_version="1",
    )


def _id_factory() -> Callable[[], str]:
    counter = itertools.count(1)
    return lambda: f"id-{next(counter)}"


def _install_insert_failure(database_path: Path, table: str) -> None:
    with connect_sqlite(database_path) as connection:
        connection.execute(
            f"""CREATE TRIGGER fail_{table}_insert
            BEFORE INSERT ON {table}
            BEGIN SELECT RAISE(ABORT, 'simulated {table} failure'); END;"""
        )


def _assert_no_start_run_participant(database_path: Path) -> None:
    with connect_sqlite(database_path) as connection:
        for table in (
            "runs",
            "messages",
            "resource_refs",
            "workflow_bindings",
            "workflow_handoffs",
            "command_receipts",
            "audit_events",
            "trace_events",
        ):
            assert _count(connection, table) == 0


def _count(connection: sqlite3.Connection, table: str) -> int:
    return int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
