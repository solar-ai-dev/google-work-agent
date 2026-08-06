import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application import (
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunService,
)
from google_work_agent.domain import ResultCode, RunStatus


@pytest.fixture()
def answer_only_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "answer-only.db"
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


def test_answer_only_completion_is_atomic(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
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
    assert response.result_code is ResultCode.TRANSITION_APPLIED
    assert response.current_status is RunStatus.COMPLETED
    assert response.current_version == 1
    assert response.assistant_message_id == "message-1"

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        message = connection.execute(
            """
            SELECT id, role, content
            FROM messages
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        receipt = connection.execute(
            """
            SELECT status, result_code, result_version
            FROM command_receipts
            WHERE command_id = 'command-1';
            """
        ).fetchone()
        audit = connection.execute(
            """
            SELECT event_type, outcome
            FROM audit_events
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        aggregate_counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans WHERE run_id = 'run-1') AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count,
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()

        assert run["status"] == "COMPLETED"
        assert run["version"] == 1
        assert run["finished_at_ms"] == 1000
        assert [(row["id"], row["role"], row["content"]) for row in message] == [
            ("message-1", "ASSISTANT", "done")
        ]
        assert receipt["status"] == "APPLIED"
        assert receipt["result_code"] == "TRANSITION_APPLIED"
        assert receipt["result_version"] == 1
        assert [(row["event_type"], row["outcome"]) for row in audit] == [
            ("RUN_COMPLETED", "TRANSITION_APPLIED")
        ]
        assert tuple(aggregate_counts) == (0, 0, 0, 0, 0)
    finally:
        connection.close()


def test_same_command_id_and_hash_returns_stored_result(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )
    command = CompleteAnswerOnlyRunCommand(
        command_id="command-1",
        conversation_id="conversation-1",
        run_id="run-1",
        assistant_message="done",
        expected_version=0,
        request_hash="a" * 64,
    )

    first = service(command)
    second = service(command)

    assert second == first

    connection = connect_sqlite(answer_only_database)
    try:
        message_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = 'run-1';"
        ).fetchone()[0]
        assert message_count == 1
    finally:
        connection.close()


def test_same_command_id_and_different_hash_is_blocked(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

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
    duplicate = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=1,
            request_hash="b" * 64,
        )
    )

    assert duplicate.applied is False
    assert duplicate.result_code is ResultCode.DUPLICATE_COMMAND
    assert duplicate.current_status is RunStatus.COMPLETED

    connection = connect_sqlite(answer_only_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 1
    finally:
        connection.close()


def test_stale_version_is_rejected_and_recorded(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-stale",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=5,
            request_hash="c" * 64,
        )
    )

    assert response.applied is False
    assert response.result_code is ResultCode.VERSION_CONFLICT
    assert response.current_status is RunStatus.ANALYZING
    assert response.current_version == 0

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute("SELECT status, version FROM runs WHERE id = 'run-1';").fetchone()
        receipt = connection.execute(
            """
            SELECT status, result_code
            FROM command_receipts
            WHERE command_id = 'command-stale';
            """
        ).fetchone()
        assert run["status"] == "ANALYZING"
        assert run["version"] == 0
        assert receipt["status"] == "REJECTED"
        assert receipt["result_code"] == "VERSION_CONFLICT"
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 0
    finally:
        connection.close()


def test_answer_only_failure_rolls_back_receipt_message_and_run(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    with pytest.raises(sqlite3.IntegrityError):
        service(
            CompleteAnswerOnlyRunCommand(
                command_id="command-fail",
                conversation_id="conversation-1",
                run_id="run-1",
                assistant_message="a" * 70000,
                expected_version=0,
                request_hash="d" * 64,
            )
        )

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run["status"] == "ANALYZING"
        assert run["version"] == 0
        assert run["finished_at_ms"] is None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM command_receipts WHERE command_id = 'command-fail';"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 0
    finally:
        connection.close()


def test_received_receipt_is_recovered_from_completed_run(answer_only_database: Path) -> None:
    connection = connect_sqlite(answer_only_database)
    try:
        connection.execute(
            """
            UPDATE runs
            SET status = 'COMPLETED', version = 1, finished_at_ms = 1000
            WHERE id = 'run-1';
            """
        )
        connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES ('message-1', 'conversation-1', 'run-1', 'ASSISTANT', 'done', 1000);
            """
        )
        connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (
                'command-pending', 'CompleteAnswerOnlyRun', ?, 'Run', 'run-1',
                'RECEIVED', 999
            );
            """,
            ("e" * 64,),
        )
    finally:
        connection.close()

    service = CompleteAnswerOnlyRunService(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 2000,
        message_id_factory=lambda: "message-2",
    )
    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-pending",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=1,
            request_hash="e" * 64,
        )
    )

    assert response.applied is True
    assert response.current_status is RunStatus.COMPLETED
    assert response.assistant_message_id == "message-1"

    connection = connect_sqlite(answer_only_database)
    try:
        receipt = connection.execute(
            """
            SELECT status, result_code, completed_at_ms
            FROM command_receipts
            WHERE command_id = 'command-pending';
            """
        ).fetchone()
        assert receipt["status"] == "APPLIED"
        assert receipt["result_code"] == "TRANSITION_APPLIED"
        assert receipt["completed_at_ms"] == 2000
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 1
    finally:
        connection.close()
