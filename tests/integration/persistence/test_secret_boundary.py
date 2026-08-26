from json import dumps, loads
from pathlib import Path
from secrets import token_urlsafe

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from google_work_agent.domain.audit_event.model import AuditEvent as AuditEventRecord
from google_work_agent.domain.trace_event.model import TraceEvent as TraceEventRecord
from google_work_agent.ports.observability_events import SanitizationError


def _secret(prefix: str) -> str:
    return f"{prefix}-{token_urlsafe(24)}"


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


def test_production_trace_and_audit_boundary_blocks_random_nested_secrets(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "secret-boundary.db"
    _seed_run(database_path)

    access_token = _secret("access")
    refresh_token = _secret("refresh")
    authorization = f"Bearer {_secret('authorization')}"
    cookie = f"session={_secret('cookie')}"
    api_key = _secret("api-key")
    code_verifier = _secret("pkce")
    page_token = _secret("page")
    attachment_bytes = _secret("attachment")

    allowed_metadata = {
        "credential_state": "READY",
        "token_expired": True,
        "page_token_present": True,
        "continuation_hash": "sha256:0123456789abcdef",
        "provider_status_code": 401,
    }
    nested_secret_payload = {
        "provider": {
            "headers": {
                "Authorization": authorization,
                "Cookie": cookie,
                "X-Api-Key": api_key,
            },
            "oauth": {
                "access_token": access_token,
                "refreshToken": refresh_token,
                "code-verifier": code_verifier,
            },
            "providerPageToken": page_token,
            "attachment": {
                "filename": "secret.txt",
                "mimeType": "text/plain",
                "attachmentId": "att-1",
                "data": attachment_bytes,
            },
        },
        **allowed_metadata,
    }

    with SqliteUnitOfWork(database_path) as unit_of_work:
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id="run-1",
                action_id=None,
                event_type="SECRET_BOUNDARY_TRACE",
                status="OK",
                duration_ms=None,
                payload_json=dumps(nested_secret_payload, sort_keys=True),
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
                metadata_json=dumps(nested_secret_payload, sort_keys=True),
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
        database_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    for secret in (
        access_token,
        refresh_token,
        authorization,
        cookie,
        api_key,
        code_verifier,
        page_token,
        attachment_bytes,
    ):
        assert secret not in trace_raw
        assert secret not in audit_raw
        assert secret not in database_dump

    trace = loads(trace_raw)
    audit = loads(audit_raw)
    for persisted in (trace, audit):
        persisted = persisted.get("attributes", persisted)
        assert persisted["credential_state"] == "READY"
        assert persisted["token_expired"] is True
        assert persisted["page_token_present"] is True
        assert persisted["continuation_hash"] == "sha256:0123456789abcdef"
        assert persisted["provider_status_code"] == 401
        provider = persisted["provider"]
        assert "providerPageToken" not in provider
        assert "data" not in provider["attachment"]
        assert "Authorization" not in provider["headers"]
        assert "Cookie" not in provider["headers"]
        assert "X-Api-Key" not in provider["headers"]
        assert "access_token" not in provider["oauth"]
        assert "refreshToken" not in provider["oauth"]
        assert "code-verifier" not in provider["oauth"]


def test_production_trace_boundary_rejects_invalid_json_fail_closed(tmp_path: Path) -> None:
    database_path = tmp_path / "secret-boundary-invalid.db"
    _seed_run(database_path)

    with SqliteUnitOfWork(database_path) as unit_of_work, pytest.raises(SanitizationError):
        unit_of_work.traces.add(
            TraceEventRecord(
                run_id="run-1",
                action_id=None,
                event_type="INVALID_SECRET_BOUNDARY_TRACE",
                status="ERROR",
                duration_ms=None,
                payload_json="not-json",
                created_at_ms=2,
            )
        )

    connection = connect_sqlite(database_path)
    try:
        count = int(
            connection.execute(
                "SELECT COUNT(*) FROM trace_events "
                "WHERE event_type = 'INVALID_SECRET_BOUNDARY_TRACE';"
            ).fetchone()[0]
        )
    finally:
        connection.close()
    assert count == 0
