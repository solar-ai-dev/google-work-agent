from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.get_supervisor_observation import (
    GetSupervisorObservationHandler,
    GetSupervisorObservationQuery,
)


def test_supervisor_observation__for_persisted_run__projects_lifecycle_facts(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "supervisor-observation.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                      'thread-1', 'AUTO', '{}', 2, 1)"""
        )

    observation = GetSupervisorObservationHandler(
        sqlite_unit_of_work_factory(database_path)
    )(GetSupervisorObservationQuery("run-1"))

    assert observation is not None
    assert observation.run_status == "PLANNING"
    assert observation.action_statuses == ()
    assert observation.cancel_intent_active is False
    assert "REQUEST_CANCEL" in observation.next_allowed_commands
