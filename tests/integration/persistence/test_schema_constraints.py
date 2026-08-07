import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite

HASH = "a" * 64


@pytest.fixture()
def migrated_connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect_sqlite(tmp_path / "constraints.db")
    apply_migrations(connection, now_ms=lambda: 1)
    try:
        yield connection
    finally:
        connection.close()


def test_schema_integrity_checks_pass(migrated_connection: sqlite3.Connection) -> None:
    assert migrated_connection.execute("PRAGMA quick_check;").fetchone()[0] == "ok"
    assert migrated_connection.execute("PRAGMA foreign_key_check;").fetchall() == []


def test_conversation_allows_only_one_open_run(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_account_conversation_and_run(migrated_connection)

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, started_at_ms
            )
            VALUES ('run-2', 'conversation-1', 'AGENT_SEARCH', 'CREATED',
                    'thread-2', 'AUTO', '{}', 101);
            """
        )


def test_action_effect_contract_blocks_invalid_combinations(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)

    with pytest.raises(sqlite3.IntegrityError):
        _insert_action(
            migrated_connection,
            action_id="action-invalid-combo",
            effect_type="READ",
            approval_requirement="REQUIRED",
            verification_policy="NONE",
            recovery_policy="NONE",
        )

    with pytest.raises(sqlite3.IntegrityError):
        _insert_action(
            migrated_connection,
            action_id="action-delete",
            effect_type="DELETE",
            approval_requirement="REQUIRED",
            verification_policy="GET_COMPARE",
            recovery_policy="GET_TARGET",
        )


def test_json_hash_and_utf8_byte_constraints(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_account_conversation_and_run(migrated_connection)

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, status,
                response_json, created_at_ms, completed_at_ms
            )
            VALUES ('command-invalid-json', 'StartRun', ?, 'Run', 'APPLIED',
                    'not-json', 1, 2);
            """,
            (HASH,),
        )

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, status,
                created_at_ms, completed_at_ms
            )
            VALUES ('command-short-hash', 'StartRun', 'short', 'Run', 'APPLIED', 1, 2);
            """
        )

    migrated_connection.execute(
        """
        INSERT INTO messages (id, conversation_id, role, content, created_at_ms)
        VALUES ('message-ok', 'conversation-1', 'USER', ?, 1);
        """,
        ("?" * 65536,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO messages (id, conversation_id, role, content, created_at_ms)
            VALUES ('message-too-large', 'conversation-1', 'USER', ?, 1);
            """,
            ("?" * 65537,),
        )


def test_only_one_active_approval_is_allowed_per_action(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-approval-1",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
    )
    migrated_connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status, approved_by_account_id,
            arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
            source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
            recovery_fingerprint, approved_at_ms, expires_at_ms
        )
        VALUES (
            'approval-1', 'action-approval-1', 1, 0, 'ACTIVE', 'account-1',
            '{}', ?, '{}', ?, '2026-08-06.p0', 'v1', ?, ?, 100, 200
        );
        """,
        (HASH, HASH, "b" * 64, "c" * 64),
    )

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms
            )
            VALUES (
                'approval-2', 'action-approval-1', 2, 0, 'ACTIVE', 'account-1',
                '{}', ?, '{}', ?, '2026-08-06.p0', 'v1', ?, ?, 101, 201
            );
            """,
            (HASH, HASH, "d" * 64, "e" * 64),
        )


def test_only_one_active_execution_attempt_is_allowed_per_approval(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-attempt-1",
        effect_type="UPDATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="GET_TARGET",
    )
    migrated_connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status, approved_by_account_id,
            arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
            source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
            recovery_fingerprint, approved_at_ms, expires_at_ms
        )
        VALUES (
            'approval-attempt-1', 'action-attempt-1', 1, 0, 'ACTIVE', 'account-1',
            '{}', ?, '{}', ?, '2026-08-06.p0', 'v1', ?, ?, 100, 200
        );
        """,
        (HASH, HASH, "d" * 64, "e" * 64),
    )
    migrated_connection.execute(
        """
        INSERT INTO execution_attempts (
            id, approval_id, attempt_no, status, started_at_ms
        )
        VALUES ('attempt-1', 'approval-attempt-1', 1, 'CLAIMED', 100);
        """
    )

    with pytest.raises(sqlite3.IntegrityError):
        migrated_connection.execute(
            """
            INSERT INTO execution_attempts (
                id, approval_id, attempt_no, status, started_at_ms
            )
            VALUES ('attempt-2', 'approval-attempt-1', 2, 'EXECUTING', 101);
            """
        )


def _insert_account_conversation_and_run(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO google_accounts (id, email, display_name, connected_at_ms)
        VALUES ('account-1', 'user@example.com', 'User', 1);
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO conversations (
            id, account_id, title, created_at_ms, updated_at_ms
        )
        VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
        """
    )
    connection.execute(
        """
        INSERT OR IGNORE INTO runs (
            id, conversation_id, entry_mode, status, langgraph_thread_id,
            requested_mode, budget_json, started_at_ms
        )
        VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED',
                'thread-1', 'AUTO', '{}', 100);
        """
    )


def _insert_plan(connection: sqlite3.Connection) -> None:
    _insert_account_conversation_and_run(connection)
    connection.execute(
        """
        INSERT OR IGNORE INTO plans (id, run_id, revision_no, status, created_at_ms)
        VALUES ('plan-1', 'run-1', 1, 'DRAFT', 100);
        """
    )


def _insert_action(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    effect_type: str,
    approval_requirement: str,
    verification_policy: str,
    recovery_policy: str,
) -> None:
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, position, tool_name, effect_type, approval_requirement,
            verification_policy, recovery_policy, status, arguments_json,
            arguments_hash, expected_json, created_at_ms, updated_at_ms
        )
        VALUES (?, 'plan-1', 1, 'gmail.search', ?, ?, ?, ?, 'PROPOSED',
                '{}', ?, '{}', 100, 100);
        """,
        (
            action_id,
            effect_type,
            approval_requirement,
            verification_policy,
            recovery_policy,
            HASH,
        ),
    )
