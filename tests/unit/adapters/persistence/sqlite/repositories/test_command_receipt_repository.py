import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository import (
    SqliteCommandReceiptRepository,
)
from google_work_agent.domain.results import ResultCode


def test_reserve_replay__and_immutable__result(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "receipts.db")
    apply_migrations(connection, now_ms=lambda: 1)
    repository = SqliteCommandReceiptRepository(connection)

    assert (
        repository.reserve_or_replay(
            command_id="command-1",
            command_type="TestCommand",
            request_hash="a" * 64,
            aggregate_type="Run",
            aggregate_id="run-1",
            created_at_ms=1,
        )
        is None
    )
    reserved = repository.reserve_or_replay(
        command_id="command-1",
        command_type="TestCommand",
        request_hash="a" * 64,
        aggregate_type="Run",
        aggregate_id="run-1",
        created_at_ms=2,
    )
    assert reserved is not None and reserved.request_hash == "a" * 64

    repository.store_result(
        command_id="command-1",
        applied=True,
        result_code=ResultCode.TRANSITION_APPLIED,
        result_version=2,
        response_json='{"applied":true}',
        completed_at_ms=3,
    )
    with pytest.raises(sqlite3.IntegrityError):
        repository.store_result(
            command_id="command-1",
            applied=False,
            result_code=ResultCode.STATE_CONFLICT,
            result_version=3,
            response_json='{"applied":false}',
            completed_at_ms=4,
        )

    replay = repository.get_by_command_id("command-1")
    assert replay is not None
    assert replay.result_code is ResultCode.TRANSITION_APPLIED
    assert replay.result_version == 2


def test_durable_cancel__intent_requires__applied_transition_receipt() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE command_receipts (
            command_type TEXT, aggregate_type TEXT, aggregate_id TEXT,
            status TEXT, result_code TEXT
        )"""
    )
    repository = SqliteCommandReceiptRepository(connection)
    assert repository.has_durable_cancel_intent("run-1") is False

    connection.execute(
        "INSERT INTO command_receipts VALUES (?, ?, ?, ?, ?)",
        ("RequestRunCancellation", "Run", "run-1", "APPLIED", "TRANSITION_APPLIED"),
    )

    assert repository.has_durable_cancel_intent("run-1") is True
