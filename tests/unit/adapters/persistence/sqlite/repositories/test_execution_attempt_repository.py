import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (
    SqliteExecutionAttemptRepository,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)


def test_execution_attempt_repository_exact_active_and_cas_surface() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE execution_attempts (
            id TEXT PRIMARY KEY, approval_id TEXT, attempt_no INTEGER, status TEXT,
            version INTEGER, result_resource_ref_id TEXT,
            response_metadata_json TEXT, error_code TEXT, error_detail_json TEXT,
            started_at_ms INTEGER, finished_at_ms INTEGER
        )"""
    )
    repository = SqliteExecutionAttemptRepository(connection)
    repository.insert_claimed(
        ExecutionAttempt(
            id="attempt-1",
            approval_id="approval-1",
            attempt_no=1,
            status=ExecutionAttemptStatusV1.CLAIMED,
            version=0,
            result_resource_ref_id=None,
            response_metadata_json=None,
            error_code=None,
            error_detail_json=None,
            started_at_ms=1,
            finished_at_ms=None,
        )
    )

    assert repository.get("attempt-1") == repository.get_active_for_approval("approval-1")
    assert repository.update_if_version_and_status(
        "attempt-1",
        0,
        frozenset({ExecutionAttemptStatusV1.CLAIMED}),
        {"status": ExecutionAttemptStatusV1.EXECUTING, "version": 1},
    )
    assert not repository.update_if_version_and_status(
        "attempt-1",
        0,
        frozenset({ExecutionAttemptStatusV1.CLAIMED}),
        {"version": 2},
    )
