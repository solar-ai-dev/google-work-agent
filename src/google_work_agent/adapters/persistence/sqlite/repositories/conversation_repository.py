"""SQLite conversation repository."""
import sqlite3
from google_work_agent.ports.models import ConversationRecord

class SQLiteConversationRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection = connection
    def get_by_id(self, conversation_id: str) -> ConversationRecord | None:
        row = self._connection.execute("SELECT id, account_id, title, created_at_ms, updated_at_ms FROM conversations WHERE id = ?;", (conversation_id,)).fetchone()
        return None if row is None else ConversationRecord(id=str(row["id"]), account_id=str(row["account_id"]), title=str(row["title"]), created_at_ms=int(row["created_at_ms"]), updated_at_ms=int(row["updated_at_ms"]))
    def add(self, conversation: ConversationRecord) -> None:
        self._connection.execute("INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) VALUES (?, ?, ?, ?, ?);", (conversation.id, conversation.account_id, conversation.title, conversation.created_at_ms, conversation.updated_at_ms))
    def touch(self, conversation_id: str, *, updated_at_ms: int) -> None:
        self._connection.execute("UPDATE conversations SET updated_at_ms = ? WHERE id = ? AND updated_at_ms < ?;", (updated_at_ms, conversation_id, updated_at_ms))
