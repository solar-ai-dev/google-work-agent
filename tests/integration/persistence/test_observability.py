import json
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.observability import (
    MAX_PURGE_BATCH,
    PurgeBlockedError,
    PurgeObservabilityDataCommand,
    PurgeObservabilityDataService,
    StaticMaintenanceGate,
)
from google_work_agent.ports import AuditEventRecord, TraceEventRecord


@pytest.fixture()
def observability_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "observability.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'ANALYZING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()
    return database_path


def test_trace_and_audit_rows_are_wrapped_as_sanitized_envelopes(
    observability_database: Path,
) -> None:
    with sqlite_unit_of_work_factory(observability_database)() as unit_of_work:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id="run-1",
                action_id=None,
                event_type="COMMAND_RECEIVED",
                status="ANALYZING",
                duration_ms=None,
                payload_json=json.dumps(
                    {"authorization": "Bearer CANARY_AUTHORIZATION", "safe": "ok"},
                    sort_keys=True,
                ),
                created_at_ms=1000,
            )
        )
        unit_of_work.audits.add(
            AuditEventRecord(
                account_id="account-1",
                run_id="run-1",
                action_id=None,
                actor_type="AGENT",
                actor_id="svc",
                actor_display="Svc",
                event_type="COMMAND_APPLIED",
                outcome="TRANSITION_APPLIED",
                metadata_json=json.dumps(
                    {"claim_token": "CANARY_CLAIM_TOKEN", "safe": "ok"},
                    sort_keys=True,
                ),
                created_at_ms=1000,
            )
        )
        unit_of_work.commit()

    connection = connect_sqlite(observability_database)
    try:
        trace = connection.execute("SELECT payload_json FROM trace_events;").fetchone()[0]
        audit = connection.execute("SELECT metadata_json FROM audit_events;").fetchone()[0]
        assert '"schema_version": 1' in trace
        assert '"schema_version": 1' in audit
        assert "CANARY_AUTHORIZATION" not in trace
        assert "CANARY_CLAIM_TOKEN" not in audit
        assert '"safe": "ok"' in trace
        assert '"safe": "ok"' in audit
    finally:
        connection.close()


def test_trace_and_audit_cursor_queries_and_purge_work(
    observability_database: Path,
) -> None:
    connection = connect_sqlite(observability_database)
    try:
        for offset in range(3):
            connection.execute(
                """
                INSERT INTO trace_events (
                    run_id, action_id, event_type, status, duration_ms, payload_json, created_at_ms
                )
                VALUES ('run-1', NULL, 'TRACE_EVENT', 'ANALYZING', NULL, '{}', ?);
                """,
                (offset + 1,),
            )
            connection.execute(
                """
                INSERT INTO audit_events (
                    account_id, run_id, action_id, actor_type, actor_id, actor_display,
                    event_type, outcome, metadata_json, created_at_ms
                )
                VALUES ('account-1', 'run-1', NULL, 'AGENT', 'svc', 'Svc', 'AUDIT_EVENT',
                        'TRANSITION_APPLIED', '{}', ?);
                """,
                (offset + 1,),
            )
    finally:
        connection.close()

    with sqlite_unit_of_work_factory(observability_database)() as unit_of_work:
        trace_rows = unit_of_work.traces.list_by_run_after_cursor(
            run_id="run-1",
            cursor_after=1,
            limit=10,
        )
        audit_rows = unit_of_work.audits.list_by_aggregate(
            run_id="run-1",
            cursor_after=1,
            limit=10,
        )
        assert [row.id for row in trace_rows] == [2, 3]
        assert [row.id for row in audit_rows] == [2, 3]

    purge_service = PurgeObservabilityDataService(
        unit_of_work_factory=sqlite_unit_of_work_factory(observability_database),
        maintenance_gate=StaticMaintenanceGate(),
    )
    result = purge_service(PurgeObservabilityDataCommand(now_ms=100 * 24 * 60 * 60 * 1000))
    assert result.trace_deleted <= MAX_PURGE_BATCH
    assert result.audit_deleted <= MAX_PURGE_BATCH


def test_purge_is_blocked_by_active_write(observability_database: Path) -> None:
    service = PurgeObservabilityDataService(
        unit_of_work_factory=sqlite_unit_of_work_factory(observability_database),
        maintenance_gate=StaticMaintenanceGate(has_active_write=True),
    )

    with pytest.raises(PurgeBlockedError):
        service(PurgeObservabilityDataCommand(now_ms=1000))
