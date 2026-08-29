from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.start_run import StartRunCommand, StartRunHandler


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "start-run-input.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES "
            "('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
    return path


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


@pytest.mark.parametrize(
    "command",
    (
        replace(_command(), request_text=""),
        replace(_command(), request_text="가" * 21846),
        replace(_command(), entry_mode="UNKNOWN"),
        replace(_command(), requested_mode="UNKNOWN"),
        replace(_command(), entry_mode="RESOURCE_SELECTED"),
    ),
)
def test_start_run_rejects_noncanonical_input_before_any_durable_write(
    tmp_path: Path, command: StartRunCommand
) -> None:
    database_path = _database(tmp_path)
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 10,
        id_factory=lambda: "must-not-be-used",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="graph-v1",
    )

    with pytest.raises(ValueError):
        handler(command)

    with connect_sqlite(database_path) as connection:
        for table in ("command_receipts", "runs", "messages", "workflow_handoffs"):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
