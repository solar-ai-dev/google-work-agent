import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.run_repository import (
    SqliteRunRepository,
)
from google_work_agent.domain.run.model import RunCreate, RunStatusV1


def test_run_repository_exact_query_create_and_cas_surface() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE runs (
            id TEXT PRIMARY KEY, conversation_id TEXT, entry_mode TEXT, status TEXT,
            langgraph_thread_id TEXT, requested_mode TEXT, actual_runtime TEXT,
            budget_json TEXT, version INTEGER, started_at_ms INTEGER,
            finished_at_ms INTEGER, terminal_result_kind TEXT
        )"""
    )
    repository = SqliteRunRepository(connection)
    repository.create(
        RunCreate(
            id="run-1",
            conversation_id="conversation-1",
            entry_mode="AGENT_SEARCH",
            status=RunStatusV1.CREATED,
            langgraph_thread_id="thread-1",
            requested_mode="AUTO",
            actual_runtime=None,
            budget_json="{}",
            version=0,
            started_at_ms=1,
            finished_at_ms=None,
        )
    )

    assert repository.get_snapshot("run-1") == repository.get("run-1")
    assert repository.find_open_by_conversation("conversation-1") is not None
    assert [run.id for run in repository.list_open_bounded(10)] == ["run-1"]
    assert repository.update_if_version_and_status(
        "run-1",
        0,
        frozenset({RunStatusV1.CREATED}),
        {"status": RunStatusV1.ANALYZING.value, "version": 1},
    )
    assert not repository.update_if_version_and_status(
        "run-1",
        0,
        frozenset({RunStatusV1.CREATED}),
        {"version": 2},
    )
    assert repository.update_if_version_and_status(
        "run-1",
        1,
        frozenset({RunStatusV1.ANALYZING}),
        {
            "status": RunStatusV1.COMPLETED.value,
            "version": 2,
            "terminal_result_kind": "SUCCESS",
        },
    )
    assert repository.get("run-1").terminal_result_kind.value == "SUCCESS"  # type: ignore[union-attr]
    assert repository.list_open_bounded(10) == ()
