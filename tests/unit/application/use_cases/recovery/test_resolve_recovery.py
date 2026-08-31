from __future__ import annotations

from pathlib import Path

from tests.support.checkpoint import sqlite_checkpoint

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.recovery.resolve_recovery import (
    ResolveRecoveryCommandV1,
    ResolveRecoveryHandler,
    materialize_current_resolve_recovery_command,
)
from google_work_agent.domain.recovery.model import RecoveryResolution


def test_recheck_from_recovery_required_transitions_to_verifying(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert result.applied
    assert result.current_status == "VERIFYING"
    assert _count(database_path, "command_receipts") == 1
    assert _count(database_path, "recovery_contexts") == 0
    assert _audit_events(database_path) == ["RECOVERY_RESOLVED"]


def test_replay_with_same_request_hash_returns_cached_result(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    first = handler(_command("cmd-1", RecoveryResolution.RECHECK))
    second = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert first == second
    assert _count(database_path, "command_receipts") == 1


def test_cancel_without_durable_intent_fails_closed_via_domain_guard(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(_command("cmd-1", RecoveryResolution.CANCEL))

    assert result.applied is False
    assert result.result_code == "RESOLUTION_NOT_ALLOWED"
    assert _count(database_path, "command_receipts") == 1


def test_resolution_from_non_recovery_required_status_fails_closed_via_domain_guard(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(_command("cmd-1", RecoveryResolution.RECHECK))

    assert result.applied is False
    assert result.result_code == "STATE_CONFLICT"
    assert _count(database_path, "command_receipts") == 1


def test_version_conflict_does_not_mutate_child_plan_or_context(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(
        ResolveRecoveryCommandV1(
            "r-1",
            99,
            "cmd-conflict",
            "b" * 64,
            0,
            RecoveryResolution.ACCEPT_PARTIAL,
            "ACTION",
            "action-1",
        )
    )

    assert not result.applied and result.result_code == "VERSION_CONFLICT"
    with connect_sqlite(database_path) as connection:
        assert (
            connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()[0]
            == "DRAFT"
        )
        assert (
            connection.execute("SELECT status FROM actions WHERE id='action-1';").fetchone()[0]
            == "MISMATCH"
        )
        assert connection.execute("SELECT COUNT(*) FROM recovery_contexts;").fetchone()[0] == 1


def test_context_version_conflict_does_not_mutate_child_plan_or_context(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(
        ResolveRecoveryCommandV1(
            run_id="r-1",
            expected_version=0,
            command_id="cmd-context-conflict",
            request_hash="d" * 64,
            recovery_context_version=99,
            resolution=RecoveryResolution.ACCEPT_PARTIAL,
            target_kind="ACTION",
            target_action_id="action-1",
        )
    )

    assert not result.applied and result.result_code == "VERSION_CONFLICT"
    with connect_sqlite(database_path) as connection:
        assert connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()[0] == (
            "DRAFT"
        )
        assert (
            connection.execute("SELECT status FROM actions WHERE id='action-1';").fetchone()[0]
            == "MISMATCH"
        )
        assert (
            connection.execute(
                "SELECT version FROM recovery_contexts WHERE run_id='r-1';"
            ).fetchone()[0]
            == 0
        )


def test_external_request_materializes_exact_current_context_binding(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)

    command = materialize_current_resolve_recovery_command(
        factory,
        run_id="r-1",
        expected_version=0,
        command_id="cmd-materialized",
        request_hash="e" * 64,
        resolution=RecoveryResolution.RECHECK,
    )

    assert command.recovery_context_version == 0
    assert command.target_kind == "ACTION"
    assert command.target_action_id == "action-1"


def test_requested_target_mismatch_does_not_mutate_child_plan_or_context(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )

    result = handler(
        ResolveRecoveryCommandV1(
            run_id="r-1",
            expected_version=0,
            command_id="cmd-target-conflict",
            request_hash="c" * 64,
            recovery_context_version=0,
            resolution=RecoveryResolution.ACCEPT_PARTIAL,
            target_kind="RUN",
        )
    )

    assert not result.applied and result.result_code == "STATE_CONFLICT"
    with connect_sqlite(database_path) as connection:
        assert connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()[0] == (
            "DRAFT"
        )
        assert (
            connection.execute("SELECT status FROM actions WHERE id='action-1';").fetchone()[0]
            == "MISMATCH"
        )
        assert connection.execute("SELECT COUNT(*) FROM recovery_contexts;").fetchone()[0] == 1


def test_fail_settles_plan_clears_context_and_writes_terminal_message(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    with connect_sqlite(database_path) as connection:
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, status, arguments_json,
                arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms
            ) VALUES (
                'action-pending', 'plan-1', 2, 'tasks_create_task', 'CREATE', 'REQUIRED',
                'GET_COMPARE', 'RESOURCE_SEARCH', 'PROPOSED', '{}', ?, '{}', '{}', 0, 1, 1
            );
            """,
            ("b" * 64,),
        )
        connection.commit()
    handler = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
        next_id=lambda: "terminal-message-1",
    )

    result = handler(_command("cmd-fail", RecoveryResolution.FAIL))

    assert result.applied and result.current_status == "FAILED"
    with connect_sqlite(database_path) as connection:
        assert (
            connection.execute("SELECT status FROM plans WHERE id='plan-1';").fetchone()[0]
            == "CANCELLED"
        )
        assert (
            connection.execute("SELECT status FROM actions WHERE id='action-pending';").fetchone()[
                0
            ]
            == "BLOCKED"
        )
        assert connection.execute("SELECT COUNT(*) FROM recovery_contexts;").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT role FROM messages WHERE id='terminal-message-1';"
            ).fetchone()[0]
            == "ASSISTANT"
        )
    assert _audit_events(database_path) == ["RECOVERY_RESOLVED"]


def test_fail_rejects_executed_action_awaiting_verification(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    with connect_sqlite(database_path) as connection:
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, status, arguments_json,
                arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms
            ) VALUES (
                'action-executed', 'plan-1', 2, 'tasks_create_task', 'CREATE', 'REQUIRED',
                'GET_COMPARE', 'RESOURCE_SEARCH', 'EXECUTED', '{}', ?, '{}', '{}', 1, 1, 1
            );
            """,
            ("b" * 64,),
        )
        connection.commit()

    result = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
    )(_command("cmd-fail-unverified", RecoveryResolution.FAIL))

    assert not result.applied and result.result_code == "RESOLUTION_NOT_ALLOWED"
    with connect_sqlite(database_path) as connection:
        assert connection.execute("SELECT status FROM runs WHERE id='r-1';").fetchone()[0] == (
            "RECOVERY_REQUIRED"
        )
        assert connection.execute("SELECT COUNT(*) FROM recovery_contexts;").fetchone()[0] == 1


def test_accept_partial_writes_required_completion_audit(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="RECOVERY_REQUIRED")
    result = ResolveRecoveryHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
        checkpoint_port=sqlite_checkpoint(database_path),
        next_id=lambda: "terminal-message-1",
    )(_command("cmd-partial", RecoveryResolution.ACCEPT_PARTIAL))

    assert result.applied and result.current_status == "COMPLETED"
    assert _audit_events(database_path) == ["RECOVERY_RESOLVED", "RUN_COMPLETED"]


def _command(command_id: str, resolution: RecoveryResolution) -> ResolveRecoveryCommandV1:
    return ResolveRecoveryCommandV1(
        run_id="r-1",
        expected_version=0,
        command_id=command_id,
        request_hash="a" * 64,
        recovery_context_version=0,
        resolution=resolution,
        target_kind="ACTION",
        target_action_id="action-1",
    )


def _count(database_path: Path, table: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()
    return int(row["n"])


def _audit_events(database_path: Path) -> list[str]:
    with connect_sqlite(database_path) as connection:
        rows = connection.execute("SELECT event_type FROM audit_events ORDER BY id;").fetchall()
    return [str(row["event_type"]) for row in rows]


def _database(tmp_path: Path, *, run_status: str) -> Path:
    path = tmp_path / "resolve-recovery.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, actual_runtime, budget_json, version, started_at_ms, finished_at_ms
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', ?, 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """,
            (run_status,),
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_disposition
            ) VALUES ('plan-1', 'r-1', 1, 'DRAFT', 'test', 1, 'REQUIRED', NULL);
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, status, arguments_json,
                arguments_hash, expected_json, risk_json, version, created_at_ms, updated_at_ms
            ) VALUES (
                'action-1', 'plan-1', 1, 'tasks_create_task', 'CREATE', 'REQUIRED',
                'GET_COMPARE', 'RESOURCE_SEARCH', 'MISMATCH', '{}',
                ?, '{}', '{}', 0, 1, 1
            );
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            INSERT INTO recovery_contexts (
                run_id, reason, scope, action_id, execution_attempt_id, verification_id,
                pre_recovery_status, recovery_fingerprint,
                observed_external_state_fingerprint, verification_input_fingerprint,
                version, created_at_ms, updated_at_ms
            ) VALUES ('r-1', 'VERIFICATION_MISMATCH', 'ACTION', 'action-1', 'attempt-1',
                      'verification-1', 'WAITING_APPROVAL', 'test-fingerprint',
                      'observed-fingerprint', 'verification-input-fingerprint', 0, 1, 1);
            """
        )
        connection.commit()
    return path
