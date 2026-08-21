"""SQLite action-dependency repository."""
import sqlite3

class SQLiteActionDependencyRepository:
    def __init__(self, connection: sqlite3.Connection) -> None: self._connection = connection
    def add(self, *, action_id: str, depends_on_action_id: str) -> None:
        self._connection.execute("INSERT INTO action_dependencies (action_id, depends_on_action_id) VALUES (?, ?);", (action_id, depends_on_action_id))
    def list_dependencies(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT depends_on_action_id FROM action_dependencies WHERE action_id = ? ORDER BY depends_on_action_id ASC;", (action_id,)).fetchall()
        return tuple(str(row["depends_on_action_id"]) for row in rows)
    def list_dependents(self, action_id: str) -> tuple[str, ...]:
        rows = self._connection.execute("SELECT action_id FROM action_dependencies WHERE depends_on_action_id = ? ORDER BY action_id ASC;", (action_id,)).fetchall()
        return tuple(str(row["action_id"]) for row in rows)
