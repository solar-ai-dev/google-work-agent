from dataclasses import replace
from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
    RecordReviewResultHandler,
)


def test_records_only_current_review_generation_with_audit_and_replay(tmp_path: Path) -> None:
    handler = _handler(_database(tmp_path))
    command = _command()

    first = handler(command)
    replay = handler(command)

    assert first.applied
    assert replay == first
    assert _values(tmp_path / "review.db", "plans", "review_status, review_disposition") == [
        ("PASSED", "PASS")
    ]
    assert _values(tmp_path / "review.db", "audit_events", "event_type, outcome") == [
        ("REVIEW_RESULT_RECORDED", "PASS")
    ]


def test_rejects_stale_review_without_opening_the_gate(tmp_path: Path) -> None:
    handler = _handler(_database(tmp_path))

    result = handler(replace(_command(), command_id="review-stale", expected_review_version=0))

    assert not result.applied
    assert _values(tmp_path / "review.db", "plans", "review_status, review_disposition") == [
        ("REQUIRED", "None")
    ]


def _handler(path: Path) -> RecordReviewResultHandler:
    return RecordReviewResultHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )


def _command() -> RecordReviewResultCommandV1:
    return RecordReviewResultCommandV1(
        command_id="review-1",
        plan_id="p-1",
        expected_plan_version=1,
        expected_review_version=1,
        review_artifact_id="p-1:review:1",
        review_version=1,
        disposition="PASS",
        based_on_action_versions={},
    )


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "review.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'WAITING_APPROVAL', 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('p-1', 'r-1', 1, 'WAITING_APPROVAL', 1, 'REQUIRED', 1, NULL);
            """
        )
        connection.commit()
    return path


def _values(path: Path, table: str, columns: str) -> list[tuple[str, str]]:
    with connect_sqlite(path) as connection:
        rows = connection.execute(f"SELECT {columns} FROM {table} ORDER BY 1;").fetchall()
    return [tuple(str(value) for value in row) for row in rows]
