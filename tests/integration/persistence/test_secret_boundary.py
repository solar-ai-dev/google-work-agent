from json import dumps, loads
from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import SQLiteUnitOfWork
from google_work_agent.ports import AuditEventRecord, TraceEventRecord


def _seed_run(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'ANALYZING',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_trace_and_audit_never_persist_secret_or_provider_transport_canaries(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "secret-boundary.db"
    _seed_run(database_path)

    trace_payload = {
        "safe_counter": 7,
        "access_token": "CANARY_ACCESS_TOKEN_TRACE",
        "providerPageToken": "CANARY_PROVIDER_PAGE_TOKEN_TRACE",
        "nested": {
            "rawProviderResponse": "CANARY_RAW_PROVIDER_RESPONSE_TRACE",
            "attachment": {
                "filename": "secret.txt",
                "mimeType": "text/plain",
                "attachmentId": "att-1",
                "data": "CANARY_ATTACHMENT_BYTES_TRACE",
            },
        },
    }
    audit_payload = {
        "safe_outcome": "ok",
        "refresh_token": "CANARY_REFRESH_TOKEN_AUDIT",
        "nextPageToken": "CANARY_PROVIDER_PAGE_TOKEN_AUDIT",
        "providerPayload": {
            "raw": "CANARY_PROVIDER_PAYLOAD_AUDIT",
        },
        "attachmentBytes": "CANARY_ATTACHMENT_BYTES_AUDIT",
    }

    with SQLiteUnitOfWork(database_path) as unit_of_work:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id="run-1",
                action_id=None,
                event_type="SECRET_BOUNDARY_TRACE",
                status="OK",
                duration_ms=None,
                payload_json=dumps(trace_payload, sort_keys=True),
                created_at_ms=2,
            )
        )
        unit_of_work.audits.add(
            AuditEventRecord(
                account_id="account-1",
                run_id="run-1",
                action_id=None,
                actor_type="SYSTEM",
                actor_id="secret-boundary-test",
                actor_display="Secret Boundary Test",
                event_type="SECRET_BOUNDARY_AUDIT",
                outcome="OK",
                metadata_json=dumps(audit_payload, sort_keys=True),
                created_at_ms=2,
            )
        )
        unit_of_work.commit()

    connection = connect_sqlite(database_path)
    try:
        trace_raw = str(
            connection.execute(
                """
                SELECT payload_json
                FROM trace_events
                WHERE event_type = 'SECRET_BOUNDARY_TRACE';
                """
            ).fetchone()[0]
        )
        audit_raw = str(
            connection.execute(
                """
                SELECT metadata_json
                FROM audit_events
                WHERE event_type = 'SECRET_BOUNDARY_AUDIT';
                """
            ).fetchone()[0]
        )
        trace = loads(trace_raw)
        audit = loads(audit_raw)
        database_dump = "\n".join(connection.iterdump()).lower()
    finally:
        connection.close()

    assert "safe_counter" in trace_raw
    assert "safe_outcome" in audit_raw
    assert trace_payload["safe_counter"] == 7
    assert audit_payload["safe_outcome"] == "ok"

    forbidden_canaries = (
        "canary_access_token_trace",
        "canary_provider_page_token_trace",
        "canary_raw_provider_response_trace",
        "canary_attachment_bytes_trace",
        "canary_refresh_token_audit",
        "canary_provider_page_token_audit",
        "canary_provider_payload_audit",
        "canary_attachment_bytes_audit",
    )
    assert all(canary not in database_dump for canary in forbidden_canaries)

    serialized_trace = dumps(trace, sort_keys=True).lower()
    serialized_audit = dumps(audit, sort_keys=True).lower()
    assert "providerpagetoken" not in serialized_trace
    assert "nextpagetoken" not in serialized_audit
    assert "rawproviderresponse" not in serialized_trace
    assert "providerpayload" not in serialized_audit
    assert "attachmentbytes" not in serialized_audit
    assert "canary_attachment_bytes_trace" not in serialized_trace
