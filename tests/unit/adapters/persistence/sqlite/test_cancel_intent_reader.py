import sqlite3

from google_work_agent.adapters.persistence.sqlite.cancel_intent_reader import (
    SqliteCancelIntentReader,
)


def test_cancel_intent_reader_requires_applied_transition_receipt() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE command_receipts (
            command_type TEXT, aggregate_type TEXT, aggregate_id TEXT,
            status TEXT, result_code TEXT
        )"""
    )
    reader = SqliteCancelIntentReader(connection)
    assert reader.has_durable_intent("run-1") is False

    connection.execute(
        "INSERT INTO command_receipts VALUES (?, ?, ?, ?, ?)",
        ("RequestRunCancellation", "Run", "run-1", "APPLIED", "TRANSITION_APPLIED"),
    )

    assert reader.has_durable_intent("run-1") is True
