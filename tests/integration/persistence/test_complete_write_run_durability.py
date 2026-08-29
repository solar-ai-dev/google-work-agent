from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.run.complete_write_run import (
    CompleteWriteRunCommand,
    CompleteWriteRunHandler,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetRunSnapshotHandler,
    GetRunSnapshotQuery,
)
from google_work_agent.application.use_cases.run.run_terminal import RunTransitionResponse
from google_work_agent.domain.message.model import Message as MessageRecord
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork


def _seed(database_path: Path, *, action_status: str) -> None:
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        persisted_action_status = "EXECUTED" if action_status == "VERIFIED" else action_status
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        run_status = "VERIFYING" if action_status == "VERIFIED" else "WAITING_APPROVAL"
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', ?, 'thread-1',
                      'AUTO', '{}', 0, 1);
            """,
            (run_status,),
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES (
                'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 1,
                'PASSED', 1, 'PASS'
            );
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                arguments_json, arguments_hash, expected_json, created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                      'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', ?,
                      '{}', ?, '{}', 1, 1);
            """,
            (persisted_action_status, "a" * 64),
        )
        if action_status == "VERIFIED":
            connection.execute(
                """
                INSERT INTO approvals (
                    id, action_id, approval_no, action_version, status,
                    approved_by_account_id, arguments_snapshot_json,
                    canonical_arguments_hash, source_snapshot_json, source_snapshot_hash,
                    policy_version, tool_schema_version, idempotency_key,
                    recovery_fingerprint, approved_at_ms, expires_at_ms, consumed_at_ms
                ) VALUES ('approval-1', 'action-1', 1, 1, 'CONSUMED', 'account-1',
                          '{}', ?, '{}', ?, 'policy-v1', 'schema-v1', ?, ?, 1, 100, 2);
                """,
                ("b" * 64, "c" * 64, "d" * 64, "e" * 64),
            )
            connection.execute(
                """
                INSERT INTO execution_attempts (
                    id, approval_id, attempt_no, status, version,
                    response_metadata_json, started_at_ms, finished_at_ms
                ) VALUES ('attempt-1', 'approval-1', 1, 'SUCCEEDED', 1, '{}', 2, 3);
                """
            )
            connection.execute(
                """
                INSERT INTO verifications (
                    id, execution_attempt_id, verification_no, status, normalizer_version,
                    expected_json, actual_json, diff_json, verified_at_ms
                ) VALUES ('verification-1', 'attempt-1', 1, 'VERIFIED', 'v1',
                          '{}', '{}', '{}', 4);
                """
            )
            connection.execute("UPDATE actions SET status = 'VERIFIED' WHERE id = 'action-1';")
        connection.commit()
    finally:
        connection.close()


def _complete(
    database_path: Path,
    *,
    unit_of_work_factory: Callable[[], SqliteUnitOfWork] | None = None,
) -> RunTransitionResponse:
    return CompleteWriteRunHandler(
        unit_of_work_factory=(
            sqlite_unit_of_work_factory(database_path)
            if unit_of_work_factory is None
            else cast(Callable[[], UnitOfWork], unit_of_work_factory)
        ),
        now_ms=lambda: 10,
        message_id_factory=lambda: "message-final-1",
    )(
        CompleteWriteRunCommand(
            command_id="complete-write-1",
            request_hash="f" * 64,
            run_id="run-1",
            expected_version=0,
        )
    )


@pytest.mark.parametrize(
    ("action_status", "expected_kind"),
    (("VERIFIED", "SUCCESS"), ("REJECTED", "PARTIAL")),
)
def test_complete_write_run_message_and_result_survive_restart(
    tmp_path: Path, action_status: str, expected_kind: str
) -> None:
    database_path = tmp_path / f"complete-{expected_kind.lower()}.db"
    _seed(database_path, action_status=action_status)

    first = _complete(database_path)
    replay = _complete(database_path)

    assert first.applied is True
    assert first.result_kind == expected_kind
    assert replay == first
    connection = connect_sqlite(database_path)
    try:
        row = connection.execute(
            "SELECT status, terminal_result_kind FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert tuple(row) == ("COMPLETED", expected_kind)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE run_id = 'run-1' AND role = 'ASSISTANT';"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE run_id = 'run-1' "
                "AND event_type = 'RUN_COMPLETED';"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()

    snapshot = GetRunSnapshotHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path)
    )(GetRunSnapshotQuery("run-1"))
    assert snapshot is not None
    assert snapshot.terminal_result_kind == expected_kind

    with SqliteUnitOfWork(database_path) as unit_of_work, pytest.raises(sqlite3.IntegrityError):
        unit_of_work.messages.append_terminal_assistant_message(
            MessageRecord(
                id="message-final-2",
                conversation_id="conversation-1",
                run_id="run-1",
                role="ASSISTANT",
                content="duplicate",
                created_at_ms=11,
            )
        )


class _FailingAppend:
    def append(self, _value: object) -> None:
        raise RuntimeError("injected append failure")


class _FailingTerminalMessage:
    def append_terminal_assistant_message(self, _value: object) -> None:
        raise RuntimeError("injected terminal message failure")


class _FailingMessageUow(SqliteUnitOfWork):
    def __enter__(self) -> SqliteUnitOfWork:
        entered = super().__enter__()
        entered.messages = _FailingTerminalMessage()  # type: ignore[assignment]
        return entered


class _FailingAuditUow(SqliteUnitOfWork):
    def __enter__(self) -> SqliteUnitOfWork:
        entered = super().__enter__()
        entered.audits = _FailingAppend()  # type: ignore[assignment]
        return entered


@pytest.mark.parametrize("uow_type", (_FailingMessageUow, _FailingAuditUow))
def test_complete_write_run_required_effect_failure_rolls_back_everything(
    tmp_path: Path, uow_type: type[SqliteUnitOfWork]
) -> None:
    database_path = tmp_path / f"rollback-{uow_type.__name__}.db"
    _seed(database_path, action_status="VERIFIED")

    with pytest.raises(RuntimeError, match="injected"):
        _complete(database_path, unit_of_work_factory=lambda: uow_type(database_path))

    connection = connect_sqlite(database_path)
    try:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id = 'run-1'),
                (SELECT terminal_result_kind FROM runs WHERE id = 'run-1'),
                (SELECT status FROM plans WHERE id = 'plan-1'),
                (SELECT COUNT(*) FROM command_receipts),
                (SELECT COUNT(*) FROM messages WHERE role = 'ASSISTANT'),
                (SELECT COUNT(*) FROM audit_events WHERE event_type = 'RUN_COMPLETED');
            """
        ).fetchone()
        assert tuple(facts) == ("VERIFYING", None, "WAITING_APPROVAL", 0, 0, 0)
    finally:
        connection.close()
