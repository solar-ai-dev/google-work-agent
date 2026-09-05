from json import loads
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.domain.audit_event.model import AuditEvent
from google_work_agent.domain.trace_event.model import TraceEvent


def test_uow__propagates_runtime_metadata_to__audit_and_post_commit_trace(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts(id, email, connected_at_ms) VALUES (?, ?, ?)",
            ("account-1", "test@example.com", 1),
        )
        connection.execute(
            "INSERT INTO conversations VALUES (?, ?, ?, ?, ?)",
            ("conversation-1", "account-1", "Runtime metadata", 1, 1),
        )
        connection.execute(
            "INSERT INTO runs(id, conversation_id, entry_mode, status, langgraph_thread_id, "
            "requested_mode, budget_json, started_at_ms) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("run-1", "conversation-1", "AGENT_SEARCH", "CREATED", "thread-1", "AUTO", "{}", 1),
        )
        connection.commit()
    factory = sqlite_unit_of_work_factory(
        path, environment="DEVELOPMENT", release_version="0.1.0-dev",
    )
    with factory() as uow:
        uow.audits.append(AuditEvent(
            None, None, None, "SYSTEM", "system", None, "RUNTIME_CHECK", "OK", "{}", 1,
        ))
        uow.traces.append(TraceEvent("run-1", None, "RUNTIME_CHECK", "OK", 1, "{}", 1))
        uow.commit()
    with connect_sqlite(path) as connection:
        audit = connection.execute("SELECT metadata_json FROM audit_events").fetchone()[0]
        trace = connection.execute("SELECT payload_json FROM trace_events").fetchone()[0]
    for event in (audit, trace):
        assert loads(event)["environment"] == "DEVELOPMENT"
        assert loads(event)["release_version"] == "0.1.0-dev"
