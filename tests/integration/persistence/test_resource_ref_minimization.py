from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.execution_attempt.write_execution_contracts import (
    StoreWriteActionSuccessCommand,
)
from google_work_agent.application.use_cases.execution_attempt.write_recovery_contracts import (
    RecoverExistingWriteResultCommand,
)
from google_work_agent.ports.connector.contracts.google_workspace import (
    ResourceSnapshot,
    ResourceType,
)
from tests.support.legacy_write.write_recovery import RecoverExistingWriteResultService
from tests.support.legacy_write.write_result_persistence import StoreWriteActionSuccessService

CANARY = "RAW_PROVIDER_SECRET_CANARY"


def test_normal_write_success_persists_only_bounded_resource_ref(tmp_path: Path) -> None:
    database_path = tmp_path / "normal-minimal.db"
    _seed_write_state(
        database_path,
        action_status="EXECUTING",
        action_version=2,
        attempt_status="EXECUTING",
        attempt_version=1,
        run_status="EXECUTING",
    )

    response = StoreWriteActionSuccessService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 200,
    )(
        StoreWriteActionSuccessCommand(
            command_id="store-success",
            request_hash="a" * 64,
            action_id="action-1",
            attempt_id="attempt-1",
            expected_action_version=2,
            expected_attempt_version=1,
            snapshot=_provider_canary_snapshot(),
        )
    )

    assert response.applied is True
    _assert_only_bounded_projection(database_path)


def test_recovery_uses_same_bounded_resource_ref_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "recovery-minimal.db"
    _seed_write_state(
        database_path,
        action_status="UNKNOWN_RESULT",
        action_version=3,
        attempt_status="UNKNOWN_RESULT",
        attempt_version=1,
        run_status="RECOVERY_REQUIRED",
    )

    response = RecoverExistingWriteResultService(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: 200,
    )(
        RecoverExistingWriteResultCommand(
            command_id="recover-existing",
            request_hash="b" * 64,
            action_id="action-1",
            attempt_id="attempt-1",
            expected_action_version=3,
            expected_attempt_version=1,
            snapshot=_provider_canary_snapshot(),
        )
    )

    assert response.applied is True
    _assert_only_bounded_projection(database_path)


def _provider_canary_snapshot() -> ResourceSnapshot:
    return ResourceSnapshot(
        fixture_snapshot_id="provider-snapshot",
        resource_type=ResourceType.CALENDAR_EVENT,
        resource_id="event-1",
        parent_id="calendar-1",
        related_resource_ids=("calendar-1",),
        version="v1",
        recovery_fingerprint=CANARY,
        payload={
            "title": "Safe title",
            "status": "confirmed",
            "event_kind": "default",
            "transparency": "busy",
            "body": CANARY,
            "html": f"<p>{CANARY}</p>",
            "attachment_bytes": CANARY.encode(),
            "continuation_token": CANARY,
            "nested": {"secret": CANARY},
            "arbitrary_list": [CANARY, {"secret": CANARY}],
        },
    )


def _assert_only_bounded_projection(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        rows = connection.execute(
            "SELECT connector_id, title, metadata_json FROM resource_refs ORDER BY id;"
        ).fetchall()
        assert len(rows) == 1
        connector_id, title, metadata_json = tuple(rows[0])
        assert connector_id == "google_workspace"
        assert title == "Safe title"
        assert metadata_json == (
            '{"event_kind": "default", "status": "confirmed", "transparency": "busy"}'
        )
        durable_text = f"{title}\n{metadata_json}"
        assert CANARY not in durable_text
        assert "body" not in metadata_json
        assert "html" not in metadata_json
        assert "attachment" not in metadata_json
        assert "continuation" not in metadata_json
        assert "nested" not in metadata_json
        assert "arbitrary_list" not in metadata_json
    finally:
        connection.close()


def _seed_write_state(
    database_path: Path,
    *,
    action_status: str,
    action_version: int,
    attempt_status: str,
    attempt_version: int,
    run_status: str,
) -> None:
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
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', ?,
                      'thread-1', 'AUTO', '{}', 0, 1);
            """,
            ("WAITING_APPROVAL",),
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES (
                'plan-1', 'run-1', 1, 'WAITING_APPROVAL', NULL, 1, 'PASSED', 0, 'PASS'
            );
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy,
                target_resource_ref_id, status, arguments_json, arguments_hash,
                expected_json, risk_json, version, created_at_ms, updated_at_ms
            ) VALUES (
                'action-1', 'plan-1', 'google_workspace', 1,
                'calendar_create_event', 'CREATE',
                'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', NULL, 'EXECUTING', '{}', ?,
                '{}', '{}', 2, 1, 1
            );
            """,
            ("c" * 64,),
        )
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
            ) VALUES (
                'approval-1', 'action-1', 1, 1, 'CONSUMED', 'account-1', '{}', ?, '{}', ?,
                'policy-1', 'schema-1', ?, ?, 1, 999, 2
            );
            """,
            ("d" * 64, "e" * 64, "f" * 64, "1" * 64),
        )
        connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, version, started_at_ms, finished_at_ms,
                error_code, error_detail_json
            ) VALUES ('attempt-1', 'approval-1', 1, 'EXECUTING', ?, 2, NULL, NULL, NULL);
            """,
            (0 if attempt_status == "UNKNOWN_RESULT" else attempt_version,),
        )
        if attempt_status == "UNKNOWN_RESULT":
            connection.execute(
                """UPDATE execution_attempts
                   SET status='UNKNOWN_RESULT', version=?, finished_at_ms=3,
                       error_code='TIMEOUT', error_detail_json='{}'
                   WHERE id='attempt-1';""",
                (attempt_version,),
            )
            connection.execute(
                "UPDATE actions SET status=?, version=? WHERE id='action-1';",
                (action_status, action_version),
            )
        connection.execute("UPDATE plans SET status='ACTIVE' WHERE id='plan-1';")
        connection.execute("UPDATE runs SET status=? WHERE id='run-1';", (run_status,))
        connection.commit()
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()
