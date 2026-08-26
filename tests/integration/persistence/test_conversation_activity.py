"""Integration tests for conversation last-activity bookkeeping."""

from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
)


def _seeded_database(tmp_path: Path, *, conversation_updated_at_ms: int) -> Path:
    database_path = tmp_path / "conversation-activity.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-1', 'user@example.com', 'User', 1);"
        )
        connection.execute(
            "INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) "
            "VALUES ('conversation-1', 'account-1', 'Conversation', 1, ?);",
            (conversation_updated_at_ms,),
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def test_start_run_advances_the_conversations_last_activity_timestamp(tmp_path: Path) -> None:
    old_updated_at_ms = 1_000
    database_path = _seeded_database(tmp_path, conversation_updated_at_ms=old_updated_at_ms)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    new_now_ms = old_updated_at_ms + 500_000

    id_counter = iter(range(1, 100))
    handler = StartRunHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: new_now_ms,
        id_factory=lambda: f"id-{next(id_counter)}",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
    )
    response = handler(
        StartRunCommand(
            command_id="command-1",
            request_hash="a" * 64,
            conversation_id="conversation-1",
            request_text="새 메시지",
            entry_mode="AGENT_SEARCH",
            requested_mode="AUTO",
            api_contract_version="1",
        )
    )

    assert response.applied is True
    with unit_of_work_factory() as unit_of_work:
        conversation = unit_of_work.conversations.get("conversation-1")
    assert conversation is not None
    assert conversation.updated_at_ms == new_now_ms


def test_conversation_touch_never_moves_the_timestamp_backward(tmp_path: Path) -> None:
    database_path = _seeded_database(tmp_path, conversation_updated_at_ms=5_000)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)

    with unit_of_work_factory() as unit_of_work:
        unit_of_work.conversations.touch_updated_at("conversation-1", updated_at_ms=1_000)
        unit_of_work.commit()

    with unit_of_work_factory() as unit_of_work:
        conversation = unit_of_work.conversations.get("conversation-1")
    assert conversation is not None
    assert conversation.updated_at_ms == 5_000
