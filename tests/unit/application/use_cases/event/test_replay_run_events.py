"""Regression tests for event replay semantic ownership."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from google_work_agent.application.use_cases.run.get_event_replay import GetEventReplayHandler, GetEventReplayQuery
from google_work_agent.ports import InvalidReplayCursorError, ProjectionEvent, SnapshotRequiredReplayError


class FakePublisher:
    def __init__(self, *, replay_error: Exception | None = None) -> None:
        self.replay_error = replay_error
        self.replay_calls: list[tuple[str, str | None]] = []
        self.published = []

    def replay(self, *, run_id: str, after_event_id: str | None):
        self.replay_calls.append((run_id, after_event_id))
        if self.replay_error is not None:
            raise self.replay_error
        return (ProjectionEvent(event_id="7", run_id=run_id, occurred_at_ms=10, event_type="RUN_UPDATED", payload={"status": "ANALYZING"}, projection_version=1, schema_version=1),)

    def publish(self, event):
        self.published.append(event)
        return ProjectionEvent(event_id="8", run_id=event.run_id, occurred_at_ms=event.occurred_at_ms, event_type=event.event_type, payload=event.payload, projection_version=event.projection_version, schema_version=event.schema_version, action_id=event.action_id)

    def subscribe(self, run_id: str):
        raise AssertionError("application replay must not subscribe")

    def get_buffer_status(self, run_id: str):
        raise AssertionError

    def close_subscription(self, subscription):
        raise AssertionError


def _connect(path: Path):
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def _handler(tmp_path: Path, publisher: FakePublisher) -> GetEventReplayHandler:
    database_path = tmp_path / "events.db"
    with _connect(database_path) as connection:
        connection.execute("CREATE TABLE runs (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO runs(id) VALUES ('run-1')")
    return GetEventReplayHandler(database_path=database_path, connection_factory=_connect, event_publisher=publisher, now_ms=lambda: 99)


def test_replay_returns_events_without_snapshot_fallback(tmp_path: Path) -> None:
    publisher = FakePublisher()
    result = _handler(tmp_path, publisher)(GetEventReplayQuery(run_id="run-1", after_event_id="6"))
    assert result.run_exists is True
    assert result.snapshot_fallback is False
    assert result.terminate_stream is False
    assert [event.event_id for event in result.events] == ["7"]


def test_invalid_or_expired_cursor_publishes_snapshot_required(tmp_path: Path) -> None:
    for error in (InvalidReplayCursorError("bad cursor"), SnapshotRequiredReplayError("expired")):
        publisher = FakePublisher(replay_error=error)
        result = _handler(tmp_path, publisher)(GetEventReplayQuery(run_id="run-1", after_event_id="old"))
        assert result.snapshot_fallback is True
        assert result.terminate_stream is True
        assert len(publisher.published) == 1


def test_missing_run_never_touches_event_replay(tmp_path: Path) -> None:
    publisher = FakePublisher()
    result = _handler(tmp_path, publisher)(GetEventReplayQuery(run_id="missing", after_event_id=None))
    assert result.run_exists is False
    assert publisher.replay_calls == []
