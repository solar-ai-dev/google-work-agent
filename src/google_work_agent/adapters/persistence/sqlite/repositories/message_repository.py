"""SQLite message repository."""
import sqlite3
from google_work_agent.ports.models import MessageRecord

class SQLiteMessageRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection = connection
    def add(self, message: MessageRecord) -> None:
        self._connection.execute("INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms) VALUES (?, ?, ?, ?, ?, ?);", (message.id, message.conversation_id, message.run_id, message.role, message.content, message.created_at_ms))
    def find_assistant_message(self, *, run_id: str, content: str) -> MessageRecord | None:
        row = self._connection.execute("SELECT id, conversation_id, run_id, role, content, created_at_ms FROM messages WHERE run_id = ? AND role = 'ASSISTANT' AND content = ? ORDER BY created_at_ms DESC, id DESC LIMIT 1;", (run_id, content)).fetchone()
        if row is None: return None
        return MessageRecord(id=str(row["id"]), conversation_id=str(row["conversation_id"]), run_id=None if row["run_id"] is None else str(row["run_id"]), role=str(row["role"]), content=str(row["content"]), created_at_ms=int(row["created_at_ms"]))
