from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.system.memory.sse_event_buffer import InMemorySseEventBuffer
from google_work_agent.application.use_cases.sse_event.list_run_events import (
    ListRunEventsHandler,
    ListRunEventsQuery,
)
from google_work_agent.ports.system.sse_event_buffer_port import (
    RunSseEventV1,
    RunStatusSsePayloadV1,
)


def _event(run_id: str, occurred_at_ms: int) -> RunSseEventV1:
    return RunSseEventV1(
        schema_version=1,
        event_id="",
        run_id=run_id,
        action_id=None,
        occurred_at_ms=occurred_at_ms,
        event_type="run_status",
        payload=RunStatusSsePayloadV1(
            status="ANALYZING", snapshot_version=occurred_at_ms
        ),
        projection_version=1,
    )


def _handler(tmp_path: Path) -> tuple[ListRunEventsHandler, InMemorySseEventBuffer]:
    database_path = tmp_path / "events.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) VALUES ('a-1', 'a@x', 1)"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 't', 1, 1)")
        connection.execute(
            """INSERT INTO runs (id, conversation_id, entry_mode, status,
            langgraph_thread_id, requested_mode, budget_json, version, started_at_ms)
            VALUES ('run-1', 'c-1', 'AGENT_SEARCH', 'ANALYZING', 't-1', 'AUTO', '{}', 1, 1)"""
        )
    buffer = InMemorySseEventBuffer(service_instance_id="svc", capacity_per_run=2)
    return ListRunEventsHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path), event_buffer=buffer
    ), buffer


def test_lists_bounded__events_and__projects_cursor_expiry(tmp_path: Path) -> None:
    handler, buffer = _handler(tmp_path)
    for index in range(1, 4):
        buffer.append(_event("run-1", index))
    current = handler(ListRunEventsQuery("run-1", "svc:2"))
    expired = handler(ListRunEventsQuery("run-1", "invalid"))
    assert [event.event_id for event in current.events] == ["svc:3"]
    assert current.cursor_status == "OK"
    assert expired.cursor_status == "CURSOR_EXPIRED"


def test_missing_run__never_exposes__buffer_content(tmp_path: Path) -> None:
    handler, buffer = _handler(tmp_path)
    buffer.append(_event("missing", 1))
    result = handler(ListRunEventsQuery("missing"))
    assert result.run_exists is False
    assert result.events == ()
