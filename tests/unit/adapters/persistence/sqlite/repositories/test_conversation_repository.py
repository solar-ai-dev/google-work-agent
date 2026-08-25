from __future__ import annotations

import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.conversation_repository import (
    SqliteConversationRepository,
)
from google_work_agent.ports.models import ConversationRecord


def _repository() -> SqliteConversationRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE conversations (
            id TEXT PRIMARY KEY, account_id TEXT, title TEXT,
            created_at_ms INTEGER, updated_at_ms INTEGER
        )"""
    )
    return SqliteConversationRepository(connection)


def test_conversation_repository_implements_exact_keyset_surface() -> None:
    repository = _repository()
    for conversation_id, updated_at_ms in (("c-1", 10), ("c-2", 20), ("c-3", 30)):
        repository.create(
            ConversationRecord(
                id=conversation_id,
                account_id="account-1",
                title=conversation_id,
                created_at_ms=updated_at_ms,
                updated_at_ms=updated_at_ms,
            )
        )

    first, cursor = repository.list_keyset(account_id="account-1", cursor=None, page_size=2)
    second, next_cursor = repository.list_keyset(account_id="account-1", cursor=cursor, page_size=2)

    assert [item.id for item in first] == ["c-3", "c-2"]
    assert [item.id for item in second] == ["c-1"]
    assert next_cursor is None
    repository.touch_updated_at("c-1", updated_at_ms=40)
    assert repository.get("c-1").updated_at_ms == 40  # type: ignore[union-attr]
