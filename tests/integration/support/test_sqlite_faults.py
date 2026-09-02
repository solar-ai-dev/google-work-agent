import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunHandler,
)
from tests.support.fakes import (
    SQLiteFaultPlan,
    SQLiteFaultStage,
    fault_injecting_unit_of_work_factory,
)


@pytest.fixture()
def answer_only_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "answer-only-faults.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'ANALYZING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()
    return database_path


@pytest.mark.parametrize(
    "stage",
    [
        SQLiteFaultStage.AFTER_TRACE_INSERT,
        SQLiteFaultStage.AFTER_AUDIT_INSERT,
        SQLiteFaultStage.BEFORE_RECEIPT_FINALIZE,
    ],
)
def test_sqlite_fault_injection__rolls_back_answer__only_write_set(
    answer_only_database: Path,
    stage: SQLiteFaultStage,
) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=fault_injecting_unit_of_work_factory(
            answer_only_database,
            SQLiteFaultPlan(stage=stage),
        ),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    with pytest.raises(sqlite3.OperationalError):
        service(
            CompleteAnswerOnlyRunCommand(
                command_id="command-1",
                conversation_id="conversation-1",
                run_id="run-1",
                assistant_message="done",
                expected_version=0,
                request_hash="a" * 64,
            )
        )

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute("SELECT status, version, finished_at_ms FROM runs;").fetchone()
        assert run["status"] == "ANALYZING"
        assert run["version"] == 0
        assert run["finished_at_ms"] is None
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM trace_events;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM command_receipts;").fetchone()[0] == 0
    finally:
        connection.close()


def test_sqlite_fault_injection__normal_path_leaves_existing__answer_only_behavior_unchanged(
    answer_only_database: Path,
) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=fault_injecting_unit_of_work_factory(answer_only_database, None),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=0,
            request_hash="a" * 64,
        )
    )

    assert response.applied is True
    connection = connect_sqlite(answer_only_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM trace_events;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM audit_events;").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM command_receipts;").fetchone()[0] == 1
    finally:
        connection.close()
