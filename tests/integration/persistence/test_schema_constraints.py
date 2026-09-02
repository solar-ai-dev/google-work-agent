import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations

HASH = "a" * 64


@pytest.fixture()
def migrated_connection(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect_sqlite(tmp_path / "constraints.db")
    apply_migrations(connection, now_ms=lambda: 1)
    try:
        yield connection
    finally:
        connection.close()


def test_schema_integrity__checks__pass(migrated_connection: sqlite3.Connection) -> None:
    assert migrated_connection.execute("PRAGMA quick_check;").fetchone()[0] == "ok"
    assert migrated_connection.execute("PRAGMA foreign_key_check;").fetchall() == []


def test_conversation_allows__only_one__open_run(
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


def test_action_effect__contract_blocks__invalid_combinations(
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

    _insert_action(
        migrated_connection,
        action_id="action-send",
        position=1,
        effect_type="SEND",
        approval_requirement="REQUIRED",
        verification_policy="SENT_LOOKUP",
        recovery_policy="MESSAGE_SEARCH",
    )
    _insert_action(
        migrated_connection,
        action_id="action-delete-valid",
        position=2,
        effect_type="DELETE",
        approval_requirement="REQUIRED",
        verification_policy="GET_ABSENT",
        recovery_policy="GET_TARGET",
    )


def test_json_hash__and_utf8__byte_constraints(
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


def test_only_one__active_approval_is__allowed_per_action(
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
    migrated_connection.execute("UPDATE plans SET status = 'WAITING_APPROVAL' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'WAITING_APPROVAL' WHERE id = 'run-1';")
    migrated_connection.execute(
        "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = 'action-approval-1';"
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
            'approval-1', 'action-approval-1', 1, 1, 'ACTIVE', 'account-1',
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
                'approval-2', 'action-approval-1', 2, 1, 'ACTIVE', 'account-1',
                '{}', ?, '{}', ?, '2026-08-06.p0', 'v1', ?, ?, 101, 201
            );
            """,
            (HASH, HASH, "d" * 64, "e" * 64),
        )


def test_only_one_active__execution_attempt_is__allowed_per_approval(
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
    migrated_connection.execute("UPDATE plans SET status = 'WAITING_APPROVAL' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'WAITING_APPROVAL' WHERE id = 'run-1';")
    migrated_connection.execute(
        "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = 'action-attempt-1';"
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
            'approval-attempt-1', 'action-attempt-1', 1, 1, 'ACTIVE', 'account-1',
            '{}', ?, '{}', ?, '2026-08-06.p0', 'v1', ?, ?, 100, 200
        );
        """,
        (HASH, HASH, "d" * 64, "e" * 64),
    )
    migrated_connection.execute(
        "UPDATE approvals SET status = 'CONSUMED', consumed_at_ms = 101 "
        "WHERE id = 'approval-attempt-1';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'EXECUTING', version = 2 WHERE id = 'action-attempt-1';"
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


def test_active_approval__and_action_status__are_enforced_bidirectionally(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-approval-guard",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
    )
    migrated_connection.execute("UPDATE plans SET status = 'WAITING_APPROVAL' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'WAITING_APPROVAL' WHERE id = 'run-1';")
    migrated_connection.execute(
        "UPDATE actions SET status = 'REJECTED' WHERE id = 'action-approval-guard';"
    )
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTIVE_APPROVAL_ACTION"):
        _insert_approval(
            migrated_connection,
            approval_id="approval-terminal",
            action_id="action-approval-guard",
            action_version=0,
        )

    migrated_connection.execute(
        "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = 'action-approval-guard';"
    )
    _insert_approval(
        migrated_connection,
        approval_id="approval-active",
        action_id="action-approval-guard",
        action_version=1,
    )
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_PLAN_ACTIVE_APPROVAL"):
        migrated_connection.execute("UPDATE plans SET status = 'SUPERSEDED' WHERE id = 'plan-1';")
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_RUN_ACTIVE_APPROVAL"):
        migrated_connection.execute("UPDATE runs SET status = 'FAILED' WHERE id = 'run-1';")
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTION_ACTIVE_APPROVAL"):
        migrated_connection.execute(
            "UPDATE actions SET status = 'CANCELLED' WHERE id = 'action-approval-guard';"
        )

    migrated_connection.execute(
        "UPDATE approvals SET status = 'REVOKED' WHERE id = 'approval-active';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'CANCELLED' WHERE id = 'action-approval-guard';"
    )


def test_run_and_plan__terminal_states_reject__nonterminal_children_both_directions(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(migrated_connection, action_id="action-terminal-parent")

    with pytest.raises(sqlite3.IntegrityError, match="NFR019_RUN_TERMINAL_ACTIONS"):
        migrated_connection.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = 'run-1';")
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_PLAN_TERMINAL_ACTIONS"):
        migrated_connection.execute("UPDATE plans SET status = 'COMPLETED' WHERE id = 'plan-1';")

    migrated_connection.execute(
        "UPDATE actions SET status = 'REJECTED' WHERE id = 'action-terminal-parent';"
    )
    migrated_connection.execute("UPDATE plans SET status = 'COMPLETED' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = 'run-1';")

    with pytest.raises(sqlite3.IntegrityError, match="ISSUE128_ACTION_NOT_CURRENT_PLAN_AUTHORITY"):
        migrated_connection.execute(
            "UPDATE actions SET status = 'PROPOSED' WHERE id = 'action-terminal-parent';"
        )
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_TERMINAL_PARENT_ACTION"):
        _insert_action(
            migrated_connection,
            action_id="action-after-completion",
            position=2,
        )


def test_cancelled_run__rejects_unknown__result_both_directions(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-cancel-unknown",
        effect_type="UPDATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="GET_TARGET",
    )
    _claim_write_action(
        migrated_connection,
        action_id="action-cancel-unknown",
        approval_id="approval-cancel-unknown",
        attempt_id="attempt-cancel-unknown",
    )
    migrated_connection.execute(
        "UPDATE execution_attempts SET status = 'UNKNOWN_RESULT' "
        "WHERE id = 'attempt-cancel-unknown';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'UNKNOWN_RESULT' WHERE id = 'action-cancel-unknown';"
    )
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_RUN_TERMINAL_ACTIONS"):
        migrated_connection.execute("UPDATE runs SET status = 'CANCELLED' WHERE id = 'run-1';")

    migrated_connection.execute(
        "UPDATE execution_attempts SET status = 'FAILED' WHERE id = 'attempt-cancel-unknown';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'FAILED' WHERE id = 'action-cancel-unknown';"
    )
    migrated_connection.execute("UPDATE plans SET status = 'CANCELLED' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'CANCELLED' WHERE id = 'run-1';")
    with pytest.raises(sqlite3.IntegrityError, match="ISSUE128_ACTION_NOT_CURRENT_PLAN_AUTHORITY"):
        migrated_connection.execute(
            "UPDATE actions SET status = 'UNKNOWN_RESULT' WHERE id = 'action-cancel-unknown';"
        )


def test_superseded_plan_nonterminal__history_does_not__block_run_completion(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(migrated_connection, action_id="action-superseded-history")
    migrated_connection.execute("UPDATE plans SET status = 'SUPERSEDED' WHERE id = 'plan-1';")
    migrated_connection.execute("UPDATE runs SET status = 'COMPLETED' WHERE id = 'run-1';")


@pytest.mark.parametrize("verification_status", ("VERIFIED", "MISMATCH"))
def test_write_verification_terminal__fact_is_allowed__with_matching_record(
    migrated_connection: sqlite3.Connection,
    verification_status: str,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-verification-fact",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
    )
    _claim_write_action(
        migrated_connection,
        action_id="action-verification-fact",
        approval_id="approval-verification-fact",
        attempt_id="attempt-verification-fact",
    )
    migrated_connection.execute(
        "UPDATE execution_attempts SET status = 'SUCCEEDED' WHERE id = 'attempt-verification-fact';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'EXECUTED', version = 3 WHERE id = 'action-verification-fact';"
    )
    migrated_connection.execute(
        """
        INSERT INTO verifications (
            id, execution_attempt_id, verification_no, status, normalizer_version,
            expected_json, actual_json, diff_json, verified_at_ms
        ) VALUES (
            'verification-fact', 'attempt-verification-fact', 1, ?,
            'v1', '{}', '{}', '[]', 2
        );
        """,
        (verification_status,),
    )
    migrated_connection.execute(
        "UPDATE actions SET status = ?, version = 4 WHERE id = 'action-verification-fact';",
        (verification_status,),
    )

    with pytest.raises(sqlite3.IntegrityError, match="NFR019_VERIFICATION_IMMUTABLE"):
        migrated_connection.execute(
            "UPDATE verifications SET status = 'ERROR' WHERE id = 'verification-fact';"
        )


def test_write_verification__terminal_status__requires_matching_record(
    migrated_connection: sqlite3.Connection,
) -> None:
    _insert_plan(migrated_connection)
    _insert_action(
        migrated_connection,
        action_id="action-verification-missing",
        effect_type="CREATE",
        approval_requirement="REQUIRED",
        verification_policy="GET_COMPARE",
        recovery_policy="RESOURCE_SEARCH",
    )
    _claim_write_action(
        migrated_connection,
        action_id="action-verification-missing",
        approval_id="approval-verification-missing",
        attempt_id="attempt-verification-missing",
    )
    migrated_connection.execute(
        "UPDATE execution_attempts SET status = 'SUCCEEDED' "
        "WHERE id = 'attempt-verification-missing';"
    )
    migrated_connection.execute(
        "UPDATE actions SET status = 'EXECUTED', version = 3 "
        "WHERE id = 'action-verification-missing';"
    )
    with pytest.raises(sqlite3.IntegrityError, match="NFR019_ACTION_VERIFICATION"):
        migrated_connection.execute(
            "UPDATE actions SET status = 'VERIFIED' WHERE id = 'action-verification-missing';"
        )


def _insert_approval(
    connection: sqlite3.Connection,
    *,
    approval_id: str,
    action_id: str,
    action_version: int,
) -> None:
    connection.execute(
        """
        INSERT INTO approvals (
            id, action_id, approval_no, action_version, status, approved_by_account_id,
            arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
            source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
            recovery_fingerprint, approved_at_ms, expires_at_ms
        ) VALUES (?, ?, 1, ?, 'ACTIVE', 'account-1', '{}', ?, '{}', ?, 'p1', 'v1', ?, ?, 1, 2);
        """,
        (
            approval_id,
            action_id,
            action_version,
            HASH,
            HASH,
            approval_id.ljust(64, "x")[:64],
            "f" * 64,
        ),
    )


def _claim_write_action(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    approval_id: str,
    attempt_id: str,
) -> None:
    connection.execute("UPDATE plans SET status = 'WAITING_APPROVAL' WHERE id = 'plan-1';")
    connection.execute("UPDATE runs SET status = 'WAITING_APPROVAL' WHERE id = 'run-1';")
    connection.execute(
        "UPDATE actions SET status = 'APPROVED', version = 1 WHERE id = ?;", (action_id,)
    )
    _insert_approval(
        connection,
        approval_id=approval_id,
        action_id=action_id,
        action_version=1,
    )
    connection.execute(
        "UPDATE approvals SET status = 'CONSUMED', consumed_at_ms = 1 WHERE id = ?;",
        (approval_id,),
    )
    connection.execute(
        "UPDATE actions SET status = 'EXECUTING', version = 2 WHERE id = ?;", (action_id,)
    )
    connection.execute(
        """
        INSERT INTO execution_attempts (id, approval_id, attempt_no, status, started_at_ms)
        VALUES (?, ?, 1, 'CLAIMED', 1);
        """,
        (attempt_id, approval_id),
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
        INSERT OR IGNORE INTO plans (
            id, run_id, revision_no, status, created_at_ms,
            review_status, review_version, review_disposition
        ) VALUES ('plan-1', 'run-1', 1, 'DRAFT', 100, 'PASSED', 1, 'PASS');
        """
    )


def _insert_action(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    position: int = 1,
    effect_type: str = "READ",
    approval_requirement: str = "NONE",
    verification_policy: str = "NONE",
    recovery_policy: str = "NONE",
) -> None:
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, position, tool_name, effect_type, approval_requirement,
            verification_policy, recovery_policy, status, arguments_json,
            arguments_hash, expected_json, created_at_ms, updated_at_ms
        )
        VALUES (?, 'plan-1', ?, 'gmail.search', ?, ?, ?, ?, 'PROPOSED',
                '{}', ?, '{}', 100, 100);
        """,
        (
            action_id,
            position,
            effect_type,
            approval_requirement,
            verification_policy,
            recovery_policy,
            HASH,
        ),
    )
