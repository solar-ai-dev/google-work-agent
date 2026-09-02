import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations


@pytest.fixture()
def aggregate_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "plan-aggregate.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        for conversation_id in ("conversation-1", "conversation-2"):
            connection.execute(
                "INSERT INTO conversations VALUES (?, 'account-1', 'Test', 1, 1);",
                (conversation_id,),
            )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-2', 'conversation-2', 'AGENT_SEARCH', 'PLANNING',
                      'thread-2', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            "INSERT INTO plans (id, run_id, revision_no, status, created_at_ms, "
            "review_status, review_disposition) "
            "VALUES ('plan-1', 'run-1', 1, 'DRAFT', 1, 'REQUIRED', NULL);"
        )
        connection.execute(
            "INSERT INTO plans (id, run_id, revision_no, status, created_at_ms, "
            "review_status, review_disposition) "
            "VALUES ('plan-2', 'run-2', 1, 'DRAFT', 1, 'REQUIRED', NULL);"
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-1', 'run-1', 'google_workspace', 'task', 'task-1', '{}', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                metadata_json, captured_at_ms
            ) VALUES ('resource-2', 'run-2', 'google_workspace', 'task', 'task-2', '{}', 1);
            """
        )
        for action_id, plan_id, position in (
            ("action-1", "plan-1", 1),
            ("action-2", "plan-2", 1),
        ):
            connection.execute(
                """
                INSERT INTO actions (
                    id, plan_id, connector_id, position, tool_name, effect_type,
                    approval_requirement,
                    verification_policy, recovery_policy, status, arguments_json,
                    arguments_hash, expected_json, version, created_at_ms, updated_at_ms
                ) VALUES (?, ?, 'google_workspace', ?, 'gmail_get_thread',
                          'READ', 'NONE', 'NONE', 'NONE',
                          'PROPOSED', '{}', ?, '{}', 0, 1, 1);
                """,
                (action_id, plan_id, position, "a" * 64),
            )
    finally:
        connection.close()
    return database_path


def test_cross_run__resource_links__are_rejected(aggregate_database: Path) -> None:
    connection = connect_sqlite(aggregate_database)
    try:
        with pytest.raises(
            sqlite3.IntegrityError,
            match="action target resource_ref must belong to plan run",
        ):
            connection.execute(
                "UPDATE actions SET target_resource_ref_id = 'resource-2' WHERE id = 'action-1';"
            )

        with pytest.raises(
            sqlite3.IntegrityError,
            match="evidence resource_ref must belong to evidence run",
        ):
            connection.execute(
                """
                INSERT INTO evidence (
                    id, run_id, origin_type, resource_ref_id, message_id, kind,
                    excerpt, locator_json, created_at_ms
                ) VALUES ('evidence-bad-resource', 'run-1', 'GOOGLE_RESOURCE',
                          'resource-2', NULL, 'TASK', 'bad', '{}', 1);
                """
            )
    finally:
        connection.close()


def test_user_message_evidence__uses_conversation_identity__not_run_identity(
    aggregate_database: Path,
) -> None:
    connection = connect_sqlite(aggregate_database)
    try:
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('run-old', 'conversation-1', 'AGENT_SEARCH', 'COMPLETED',
                      'thread-old', 'AUTO', '{}', 1, 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES ('message-old', 'conversation-1', 'run-old', 'USER', 'older request', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO evidence (
                id, run_id, origin_type, resource_ref_id, message_id, kind,
                excerpt, locator_json, created_at_ms
            ) VALUES ('evidence-old-message', 'run-1', 'USER_MESSAGE', NULL,
                      'message-old', 'USER_REQUEST', 'older request', NULL, 1);
            """
        )

        connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES ('message-other', 'conversation-2', 'run-2', 'USER', 'other request', 1);
            """
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="user-message evidence must belong to run conversation",
        ):
            connection.execute(
                """
                INSERT INTO evidence (
                    id, run_id, origin_type, resource_ref_id, message_id, kind,
                    excerpt, locator_json, created_at_ms
                ) VALUES ('evidence-other-message', 'run-1', 'USER_MESSAGE', NULL,
                          'message-other', 'USER_REQUEST', 'other request', NULL, 1);
                """
            )
    finally:
        connection.close()


def test_cross_plan_dependency__and_cross_run__action_evidence_are_rejected(
    aggregate_database: Path,
) -> None:
    connection = connect_sqlite(aggregate_database)
    try:
        connection.execute(
            """
            INSERT INTO evidence (
                id, run_id, origin_type, resource_ref_id, message_id, kind,
                excerpt, locator_json, created_at_ms
            ) VALUES ('evidence-2', 'run-2', 'GOOGLE_RESOURCE', 'resource-2', NULL,
                      'TASK', 'task evidence', '{}', 1);
            """
        )
        with pytest.raises(
            sqlite3.IntegrityError,
            match="action evidence must belong to plan run",
        ):
            connection.execute("INSERT INTO action_evidence VALUES ('action-1', 'evidence-2');")
        with pytest.raises(
            sqlite3.IntegrityError,
            match="action dependency must remain inside one plan",
        ):
            connection.execute("INSERT INTO action_dependencies VALUES ('action-2', 'action-1');")
    finally:
        connection.close()


def test_nfr019_write__safety_triggers_survive__plan_aggregate_migration(
    aggregate_database: Path,
) -> None:
    expected = {
        "trg_approvals_active_action_guard_insert",
        "trg_approvals_active_action_guard_update",
        "trg_actions_active_approval_guard_update",
        "trg_runs_active_approval_guard_update",
        "trg_plans_inactive_approval_guard_update",
        "trg_runs_terminal_actions_guard_update",
        "trg_plans_terminal_actions_guard_update",
        "trg_actions_terminal_parent_guard_insert",
        "trg_actions_terminal_parent_guard_update",
        "trg_attempts_action_guard_insert",
        "trg_attempts_action_guard_update",
        "trg_actions_attempt_guard_update",
        "trg_verifications_action_guard_insert",
        "trg_verifications_immutable_update",
        "trg_verifications_immutable_delete",
        "trg_actions_verification_guard_update",
    }
    connection = connect_sqlite(aggregate_database)
    try:
        actual = {
            row["name"]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger';")
        }
        assert expected <= actual
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()
