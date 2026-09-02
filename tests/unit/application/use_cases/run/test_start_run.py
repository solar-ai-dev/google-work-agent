from __future__ import annotations

from dataclasses import replace
from json import loads
from pathlib import Path

import pytest
from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.start_run import StartRunCommand, StartRunHandler
from google_work_agent.ports.system.settings_port import PanelPreferencesV1, SettingsViewV1


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "start-run-input.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
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
def test_start_run_rejects__noncanonical_input_before__any_durable_write(
    tmp_path: Path, command: StartRunCommand
) -> None:
    database_path = _database(tmp_path)
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
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


def test_start_run_freezes__current_settings_into__durable_run_budget(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    handler = StartRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=lambda: 1234,
        id_factory=iter(("run-1", "message-1", "workflow-1", "handoff-1")).__next__,
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="graph-v1",
        settings_provider=lambda: SettingsViewV1(
            schema_version=1,
            timezone="UTC",
            default_tasklist_id=None,
            default_calendar_id=None,
            preferred_llm_mode="AUTO",
            external_llm_consent=False,
            retention_days=7,
            theme="LIGHT",
            panel_preferences=PanelPreferencesV1(1, False, "CONVERSATIONS"),
            working_day_start_local="09:00",
            working_day_end_local="18:00",
            include_weekends=False,
            calendar_buffer_minutes=0,
            max_run_execution_ms=60_000,
            max_connector_calls_per_run=9,
            max_source_page_calls_per_run=7,
            max_detail_fetches_per_run=11,
            max_context_tokens_per_run=4_000,
            max_retry_attempts_per_run=3,
            circuit_failure_threshold=3,
            circuit_open_duration_ms=30_000,
        ),
    )

    result = handler(_command())

    with connect_sqlite(database_path) as connection:
        budget = loads(
            connection.execute(
                "SELECT budget_json FROM runs WHERE id = ?", (result.run_id,)
            ).fetchone()[0]
        )
    assert budget["schema_version"] == 2
    assert budget["started_at_ms"] == 1234
    assert budget["max_execution_ms"] == 60_000
    assert budget["max_connector_calls"] == 9
    assert budget["max_source_page_calls"] == 7
    assert budget["max_detail_fetches"] == 11
    assert budget["max_context_tokens"] == 4_000
    assert budget["max_retry_attempts"] == 3
