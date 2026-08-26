"""Integration tests for the conversation history read projection."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.get_conversation_history import (
    GetConversationHistoryHandler,
    GetConversationHistoryQuery,
)
from google_work_agent.application.use_cases.message.list_conversation_messages import (
    MAX_HISTORY_MESSAGES,
)


class _UnusedRuntimeStatusProvider:
    def get_summary(self) -> object:
        raise NotImplementedError


def _history_handler(database_path: Path) -> GetConversationHistoryHandler:
    return GetConversationHistoryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        database_path=database_path,
        connection_factory=connect_sqlite,
    )


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "conversation-history.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', '업무 대화', 10, 60);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-2', 'account-1', '다른 대화', 10, 20);
            """
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def _insert_run(
    connection: sqlite3.Connection,
    *,
    run_id: str,
    conversation_id: str,
    status: str,
    started_at_ms: int,
    finished_at_ms: int | None,
) -> None:
    connection.execute(
        """
        INSERT INTO runs (
            id, conversation_id, entry_mode, status, langgraph_thread_id,
            requested_mode, actual_runtime, budget_json, version,
            started_at_ms, finished_at_ms
        ) VALUES (?, ?, 'AGENT_SEARCH', ?, ?, 'AUTO', NULL, '{}', 0, ?, ?);
        """,
        (
            run_id,
            conversation_id,
            status,
            f"thread-{run_id}",
            started_at_ms,
            finished_at_ms,
        ),
    )


def _insert_message(
    connection: sqlite3.Connection,
    *,
    message_id: str,
    conversation_id: str,
    run_id: str | None,
    role: str,
    content: str,
    created_at_ms: int,
) -> None:
    connection.execute(
        """
        INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
        VALUES (?, ?, ?, ?, ?, ?);
        """,
        (message_id, conversation_id, run_id, role, content, created_at_ms),
    )


def test_history_returns_every_turn_of_one_conversation_in_time_order(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    connection = connect_sqlite(database_path)
    try:
        for index in (1, 2, 3):
            _insert_run(
                connection,
                run_id=f"run-{index}",
                conversation_id="conversation-1",
                status="COMPLETED",
                started_at_ms=index * 10,
                finished_at_ms=index * 10 + 5,
            )
            _insert_message(
                connection,
                message_id=f"message-user-{index}",
                conversation_id="conversation-1",
                run_id=f"run-{index}",
                role="USER",
                content=f"요청 {index}",
                created_at_ms=index * 10,
            )
            _insert_message(
                connection,
                message_id=f"message-assistant-{index}",
                conversation_id="conversation-1",
                run_id=f"run-{index}",
                role="ASSISTANT",
                content=f"응답 {index}",
                created_at_ms=index * 10 + 5,
            )
        _insert_run(
            connection,
            run_id="run-other",
            conversation_id="conversation-2",
            status="COMPLETED",
            started_at_ms=1,
            finished_at_ms=2,
        )
        _insert_message(
            connection,
            message_id="message-other",
            conversation_id="conversation-2",
            run_id="run-other",
            role="USER",
            content="다른 대화 요청",
            created_at_ms=1,
        )
        connection.commit()
    finally:
        connection.close()

    history = _history_handler(database_path)(
        GetConversationHistoryQuery(conversation_id="conversation-1")
    )

    assert history is not None
    assert history.conversation.id == "conversation-1"
    assert [(item.role, item.content) for item in history.messages] == [
        ("USER", "요청 1"),
        ("ASSISTANT", "응답 1"),
        ("USER", "요청 2"),
        ("ASSISTANT", "응답 2"),
        ("USER", "요청 3"),
        ("ASSISTANT", "응답 3"),
    ]
    assert [item.run_id for item in history.runs] == ["run-1", "run-2", "run-3"]
    assert history.truncated is False


def test_history_keeps_a_failed_run_and_an_open_run_in_the_projection(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    connection = connect_sqlite(database_path)
    try:
        _insert_run(
            connection,
            run_id="run-failed",
            conversation_id="conversation-1",
            status="FAILED",
            started_at_ms=10,
            finished_at_ms=15,
        )
        _insert_run(
            connection,
            run_id="run-open",
            conversation_id="conversation-1",
            status="PLANNING",
            started_at_ms=20,
            finished_at_ms=None,
        )
        _insert_message(
            connection,
            message_id="message-1",
            conversation_id="conversation-1",
            run_id="run-failed",
            role="USER",
            content="실패한 요청",
            created_at_ms=10,
        )
        _insert_message(
            connection,
            message_id="message-2",
            conversation_id="conversation-1",
            run_id="run-open",
            role="USER",
            content="진행 중 요청",
            created_at_ms=20,
        )
        connection.commit()
    finally:
        connection.close()

    history = _history_handler(database_path)(
        GetConversationHistoryQuery(conversation_id="conversation-1")
    )

    assert history is not None
    assert [(item.run_id, item.status, item.finished_at_ms) for item in history.runs] == [
        ("run-failed", "FAILED", 15),
        ("run-open", "PLANNING", None),
    ]
    assert [item.content for item in history.messages] == ["실패한 요청", "진행 중 요청"]


def test_history_is_empty_for_a_conversation_without_messages(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    history = _history_handler(database_path)(
        GetConversationHistoryQuery(conversation_id="conversation-1")
    )

    assert history is not None
    assert history.messages == ()
    assert history.runs == ()
    assert history.truncated is False


def test_history_is_none_for_an_unknown_conversation(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)

    assert (
        _history_handler(database_path)(GetConversationHistoryQuery(conversation_id="missing"))
        is None
    )


def test_history_keeps_the_newest_messages_and_reports_truncation(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path)
    total = MAX_HISTORY_MESSAGES + 5
    connection = connect_sqlite(database_path)
    try:
        for index in range(total):
            _insert_message(
                connection,
                message_id=f"message-{index:04d}",
                conversation_id="conversation-1",
                run_id=None,
                role="USER",
                content=f"요청 {index}",
                created_at_ms=index + 1,
            )
        connection.commit()
    finally:
        connection.close()

    history = _history_handler(database_path)(
        GetConversationHistoryQuery(conversation_id="conversation-1")
    )

    assert history is not None
    assert history.truncated is True
    assert len(history.messages) == MAX_HISTORY_MESSAGES
    assert history.messages[0].content == f"요청 {total - MAX_HISTORY_MESSAGES}"
    assert history.messages[-1].content == f"요청 {total - 1}"
