from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.conversation.create_conversation import (
    CreateConversationCommand,
    CreateConversationHandler,
)


def test_create_conversation__persists_through__unit_of_work(tmp_path: Path) -> None:
    database_path = tmp_path / "create.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            """INSERT INTO google_accounts (id, email, connected_at_ms)
            VALUES ('a-1', 'u@example.com', 1)"""
        )
    handler = CreateConversationHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 10,
    )

    result = handler(
        CreateConversationCommand(
            command_id="cmd-1",
            request_hash="a" * 64,
            conversation_id="c-1",
            account_id="a-1",
            title="title",
            api_contract_version="1",
        )
    )

    assert result.applied is True
    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        assert unit_of_work.conversations.get("c-1") is not None
