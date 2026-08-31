from __future__ import annotations

import sqlite3

import pytest

from google_work_agent.adapters.persistence.sqlite.repositories.message_repository import (
    SqliteMessageRepository,
)
from google_work_agent.domain.message.model import Message as MessageRecord


def _repository() -> SqliteMessageRepository:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE messages (
            id TEXT PRIMARY KEY, conversation_id TEXT, run_id TEXT,
            role TEXT, content TEXT, created_at_ms INTEGER
        )"""
    )
    return SqliteMessageRepository(connection)


def test_message_repository_appends_owned_roles_and_lists_keyset() -> None:
    repository = _repository()
    repository.append_user_message(MessageRecord("m-1", "c-1", "r-1", "USER", "q", 10))
    repository.append_terminal_assistant_message(
        MessageRecord("m-2", "c-1", "r-1", "ASSISTANT", "a", 20)
    )

    messages, cursor = repository.list_by_conversation_keyset(
        conversation_id="c-1", cursor=None, page_size=10
    )

    assert [item.id for item in messages] == ["m-2", "m-1"]
    assert cursor is None
    assert [item.id for item in messages if item.run_id == "r-1"][:1] == ["m-2"]


def test_message_repository_rejects_cross_role_append() -> None:
    repository = _repository()
    with pytest.raises(ValueError):
        repository.append_user_message(MessageRecord("m-1", "c-1", "r-1", "ASSISTANT", "a", 10))
