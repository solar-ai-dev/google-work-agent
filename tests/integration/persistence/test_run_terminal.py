from collections.abc import Callable
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import (
    apply_migrations,
    connect_sqlite,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.run.block_run import (
    BlockRunCommand,
    BlockRunHandler,
)
from google_work_agent.application.use_cases.run.run_terminal import (
    FailRunCommand,
    FailRunService,
    RunTransitionResponse,
)

TerminalCommand = BlockRunCommand | FailRunCommand
TerminalService = Callable[..., RunTransitionResponse]
TerminalServiceFactory = Callable[[Path], TerminalService]


@pytest.fixture()
def run_terminal_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "run-terminal.db"
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


def _set_run_status(database_path: Path, *, status: str, version: int = 0) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            """
            UPDATE runs
            SET status = ?, version = ?, finished_at_ms = NULL
            WHERE id = 'run-1';
            """,
            (status, version),
        )
    finally:
        connection.close()


def _insert_active_approval(database_path: Path) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "INSERT INTO plans (id, run_id, revision_no, status, created_at_ms, "
            "review_status, review_version, review_disposition) "
            "VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 1, 'PASSED', 1, 'PASS');"
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, position, tool_name, effect_type, approval_requirement,
                verification_policy, recovery_policy, status, arguments_json,
                arguments_hash, expected_json, version, created_at_ms, updated_at_ms
            ) VALUES (
                'action-1', 'plan-1', 1, 'calendar.create', 'CREATE', 'REQUIRED',
                'GET_COMPARE', 'RESOURCE_SEARCH', 'APPROVED', '{}', ?, '{}', 1, 1, 1
            );
            """,
            ("a" * 64,),
        )
        connection.execute(
            """
            INSERT INTO approvals (
                id, action_id, approval_no, action_version, status, approved_by_account_id,
                arguments_snapshot_json, canonical_arguments_hash, source_snapshot_json,
                source_snapshot_hash, policy_version, tool_schema_version, idempotency_key,
                recovery_fingerprint, approved_at_ms, expires_at_ms
            ) VALUES (
                'approval-1', 'action-1', 1, 1, 'ACTIVE', 'account-1', '{}', ?, '{}', ?,
                'p1', 'v1', ?, ?, 1, 2000
            );
            """,
            ("b" * 64, "c" * 64, "d" * 64, "e" * 64),
        )
        connection.commit()
    finally:
        connection.close()


@pytest.mark.parametrize(
    (
        "service_factory",
        "command",
        "initial_status",
        "expected_status",
        "event_type",
        "finished_at_ms",
    ),
    (
        (
            lambda path: BlockRunHandler(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            BlockRunCommand(
                command_id="command-block",
                request_hash="a" * 64,
                run_id="run-1",
                expected_version=0,
                reason_code="INTENT_UNSUPPORTED_SCOPE",
            ),
            "PLANNING",
            "BLOCKED",
            "RUN_BLOCKED",
            1000,
        ),
        (
            lambda path: FailRunService(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            FailRunCommand(
                command_id="command-fail",
                request_hash="b" * 64,
                run_id="run-1",
                expected_version=0,
                reason_code="OUTPUT_SCHEMA_INVALID",
            ),
            "ANALYZING",
            "RECOVERY_REQUIRED",
            "RUN_RECOVERY_REQUIRED",
            None,
        ),
    ),
)
def test_run_terminal_services_persist_transition_receipt_and_events(
    run_terminal_database: Path,
    service_factory: TerminalServiceFactory,
    command: TerminalCommand,
    initial_status: str,
    expected_status: str,
    event_type: str,
    finished_at_ms: int | None,
) -> None:
    _set_run_status(run_terminal_database, status=initial_status)
    service = service_factory(run_terminal_database)

    response = service(command)

    assert response.applied is True
    assert response.run_status == expected_status
    assert response.run_version == 1
    assert response.reason_code == command.reason_code

    connection = connect_sqlite(run_terminal_database)
    try:
        run = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        receipt = connection.execute(
            """
            SELECT status, result_code, result_version
            FROM command_receipts
            WHERE command_id = ?;
            """,
            (command.command_id,),
        ).fetchone()
        trace = connection.execute(
            """
            SELECT event_type, status
            FROM trace_events
            WHERE run_id = 'run-1'
            ORDER BY created_at_ms DESC
            LIMIT 1;
            """
        ).fetchone()
        audit = connection.execute(
            """
            SELECT event_type, outcome
            FROM audit_events
            WHERE run_id = 'run-1'
            ORDER BY created_at_ms DESC
            LIMIT 1;
            """
        ).fetchone()
        assert run["status"] == expected_status
        assert run["version"] == 1
        assert run["finished_at_ms"] == finished_at_ms
        assert receipt["status"] == "APPLIED"
        assert receipt["result_code"] == "TRANSITION_APPLIED"
        assert receipt["result_version"] == 1
        assert trace["event_type"] == event_type
        assert trace["status"] == expected_status
        assert audit["event_type"] == event_type
        assert audit["outcome"] == "TRANSITION_APPLIED"
    finally:
        connection.close()


def test_block_run_revokes_active_approval_before_terminal_transition(
    run_terminal_database: Path,
) -> None:
    _set_run_status(run_terminal_database, status="WAITING_APPROVAL")
    _insert_active_approval(run_terminal_database)
    service = BlockRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(run_terminal_database),
        now_ms=lambda: 1000,
    )

    response = service(
        BlockRunCommand(
            command_id="command-block-active-approval",
            request_hash="1" * 64,
            run_id="run-1",
            expected_version=0,
            reason_code="POLICY_BLOCKED",
        )
    )

    assert response.applied is True
    connection = connect_sqlite(run_terminal_database)
    try:
        assert (
            connection.execute("SELECT status FROM approvals WHERE id = 'approval-1';").fetchone()[
                0
            ]
            == "REVOKED"
        )
    finally:
        connection.close()


def test_block_run_version_conflict_does_not_revoke_active_approval(
    run_terminal_database: Path,
) -> None:
    _set_run_status(run_terminal_database, status="WAITING_APPROVAL")
    _insert_active_approval(run_terminal_database)
    service = BlockRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(run_terminal_database),
        now_ms=lambda: 1000,
    )

    response = service(
        BlockRunCommand(
            command_id="command-block-active-approval-conflict",
            request_hash="2" * 64,
            run_id="run-1",
            expected_version=9,
            reason_code="POLICY_BLOCKED",
        )
    )

    assert response.applied is False
    assert response.result_code == "VERSION_CONFLICT"
    connection = connect_sqlite(run_terminal_database)
    try:
        assert (
            connection.execute("SELECT status FROM approvals WHERE id = 'approval-1';").fetchone()[
                0
            ]
            == "ACTIVE"
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("service_factory", "command", "initial_status"),
    (
        (
            lambda path: BlockRunHandler(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            BlockRunCommand(
                command_id="command-block-repeat",
                request_hash="d" * 64,
                run_id="run-1",
                expected_version=0,
                reason_code="INTENT_UNSUPPORTED_SCOPE",
            ),
            "ANALYZING",
        ),
        (
            lambda path: FailRunService(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            FailRunCommand(
                command_id="command-fail-repeat",
                request_hash="e" * 64,
                run_id="run-1",
                expected_version=0,
                reason_code="OUTPUT_SCHEMA_INVALID",
            ),
            "RETRIEVING",
        ),
    ),
)
def test_run_terminal_services_return_stored_result_for_same_command_id_and_hash(
    run_terminal_database: Path,
    service_factory: TerminalServiceFactory,
    command: TerminalCommand,
    initial_status: str,
) -> None:
    _set_run_status(run_terminal_database, status=initial_status)
    service = service_factory(run_terminal_database)

    first = service(command)
    second = service(command)

    assert second == first


@pytest.mark.parametrize(
    ("service_factory", "command", "initial_status", "expected_status"),
    (
        (
            lambda path: BlockRunHandler(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            BlockRunCommand(
                command_id="command-block-stale",
                request_hash="g" * 64,
                run_id="run-1",
                expected_version=9,
                reason_code="INTENT_UNSUPPORTED_SCOPE",
            ),
            "ANALYZING",
            "ANALYZING",
        ),
        (
            lambda path: FailRunService(
                unit_of_work_factory=sqlite_unit_of_work_factory(path),
                now_ms=lambda: 1000,
            ),
            FailRunCommand(
                command_id="command-fail-stale",
                request_hash="h" * 64,
                run_id="run-1",
                expected_version=9,
                reason_code="OUTPUT_SCHEMA_INVALID",
            ),
            "RETRIEVING",
            "RETRIEVING",
        ),
    ),
)
def test_run_terminal_services_reject_stale_version_and_record_receipt(
    run_terminal_database: Path,
    service_factory: TerminalServiceFactory,
    command: TerminalCommand,
    initial_status: str,
    expected_status: str,
) -> None:
    _set_run_status(run_terminal_database, status=initial_status)
    service = service_factory(run_terminal_database)

    response = service(command)

    assert response.applied is False
    assert response.result_code == "VERSION_CONFLICT"
    assert response.run_status == expected_status
    assert response.run_version == 0

    connection = connect_sqlite(run_terminal_database)
    try:
        receipt = connection.execute(
            """
            SELECT status, result_code, result_version
            FROM command_receipts
            WHERE command_id = ?;
            """,
            (command.command_id,),
        ).fetchone()
        assert receipt["status"] == "REJECTED"
        assert receipt["result_code"] == "VERSION_CONFLICT"
        assert receipt["result_version"] == 0
    finally:
        connection.close()
