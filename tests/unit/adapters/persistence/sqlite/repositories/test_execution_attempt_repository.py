import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (  # noqa: E501
    SqliteExecutionAttemptRepository,
)
from google_work_agent.domain.execution_attempt.model import (
    ExecutionAttempt,
    ExecutionAttemptStatusV1,
)


def _reconciliation_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE runs (id TEXT PRIMARY KEY, status TEXT NOT NULL);
        CREATE TABLE plans (
            id TEXT PRIMARY KEY, run_id TEXT NOT NULL, revision_no INTEGER NOT NULL,
            status TEXT NOT NULL
        );
        CREATE TABLE actions (
            id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, status TEXT NOT NULL
        );
        CREATE TABLE approvals (id TEXT PRIMARY KEY, action_id TEXT NOT NULL);
        CREATE TABLE execution_attempts (
            id TEXT PRIMARY KEY, approval_id TEXT NOT NULL, status TEXT NOT NULL,
            started_at_ms INTEGER NOT NULL
        );
        CREATE TABLE command_receipts (
            command_id TEXT PRIMARY KEY, command_type TEXT NOT NULL,
            aggregate_type TEXT NOT NULL, aggregate_id TEXT, status TEXT NOT NULL,
            result_code TEXT
        );
        CREATE TABLE recovery_contexts (
            run_id TEXT, reason TEXT, action_id TEXT, execution_attempt_id TEXT
        );
        CREATE TABLE verifications (execution_attempt_id TEXT);
        CREATE TABLE action_dependencies (
            action_id TEXT, depends_on_action_id TEXT
        );
        """
    )
    return connection


def _seed_failed_attempt(
    connection: sqlite3.Connection,
    *,
    suffix: str,
    run_status: str,
    plan_status: str = "WAITING_APPROVAL",
    revision_no: int = 1,
    started_at_ms: int = 1,
) -> None:
    connection.execute("INSERT INTO runs VALUES (?, ?)", (f"run-{suffix}", run_status))
    connection.execute(
        "INSERT INTO plans VALUES (?, ?, ?, ?)",
        (f"plan-{suffix}", f"run-{suffix}", revision_no, plan_status),
    )
    connection.execute(
        "INSERT INTO actions VALUES (?, ?, 'FAILED')",
        (f"action-{suffix}", f"plan-{suffix}"),
    )
    connection.execute(
        "INSERT INTO approvals VALUES (?, ?)",
        (f"approval-{suffix}", f"action-{suffix}"),
    )
    connection.execute(
        "INSERT INTO execution_attempts VALUES (?, ?, 'FAILED', ?)",
        (f"attempt-{suffix}", f"approval-{suffix}", started_at_ms),
    )
    connection.execute(
        "INSERT INTO command_receipts VALUES (?, 'ResolveAsFailed', "
        "'ExecutionAttempt', ?, 'APPLIED', 'TRANSITION_APPLIED')",
        (
            f"system:execution-attempt-reconcile:attempt-{suffix}:resolve-failed",
            f"attempt-{suffix}",
        ),
    )


def test_execution_attempt_repository_exact_active_and_cas_surface() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute(
        """CREATE TABLE execution_attempts (
            id TEXT PRIMARY KEY, approval_id TEXT, attempt_no INTEGER, status TEXT,
            version INTEGER, result_resource_ref_id TEXT,
            response_metadata_json TEXT, error_code TEXT, error_detail_json TEXT,
            started_at_ms INTEGER, finished_at_ms INTEGER
        )"""
    )
    repository = SqliteExecutionAttemptRepository(connection)
    repository.insert_claimed(
        ExecutionAttempt(
            id="attempt-1",
            approval_id="approval-1",
            attempt_no=1,
            status=ExecutionAttemptStatusV1.CLAIMED,
            version=0,
            result_resource_ref_id=None,
            response_metadata_json=None,
            error_code=None,
            error_detail_json=None,
            started_at_ms=1,
            finished_at_ms=None,
        )
    )

    assert repository.get("attempt-1") == repository.get_active_for_approval("approval-1")
    assert not hasattr(repository, "get_latest_for_approval")
    assert repository.update_if_version_and_status(
        "attempt-1",
        0,
        frozenset({ExecutionAttemptStatusV1.CLAIMED}),
        {"status": ExecutionAttemptStatusV1.EXECUTING, "version": 1},
    )
    assert not repository.update_if_version_and_status(
        "attempt-1",
        0,
        frozenset({ExecutionAttemptStatusV1.CLAIMED}),
        {"version": 2},
    )


def test_reconciliation_candidates_use_exact_current_continuation_predicates() -> None:
    connection = _reconciliation_connection()
    repository = SqliteExecutionAttemptRepository(connection)

    _seed_failed_attempt(
        connection,
        suffix="cancel",
        run_status="CANCEL_REQUESTED",
        started_at_ms=1,
    )
    connection.execute(
        "INSERT INTO command_receipts VALUES "
        "('cancel-run-cancel', 'RequestRunCancellation', 'Run', 'run-cancel', "
        "'APPLIED', 'TRANSITION_APPLIED')"
    )

    _seed_failed_attempt(
        connection,
        suffix="continue",
        run_status="WAITING_APPROVAL",
        started_at_ms=2,
    )
    connection.execute(
        "INSERT INTO actions VALUES ('action-continue-next', 'plan-continue', 'APPROVED')"
    )

    _seed_failed_attempt(
        connection,
        suffix="stable",
        run_status="WAITING_APPROVAL",
        started_at_ms=3,
    )

    candidates = repository.list_reconciliation_candidates(10)

    assert [(candidate.execution_attempt_id, candidate.kind) for candidate in candidates] == [
        ("attempt-cancel", "FAILED_AWAITING_CONTINUATION"),
        ("attempt-continue", "FAILED_AWAITING_CONTINUATION"),
    ]


def test_reconciliation_candidates_use_exact_phase_markers() -> None:
    connection = _reconciliation_connection()
    repository = SqliteExecutionAttemptRepository(connection)
    phases = (
        ("pre-begin", "CLAIMED", "EXECUTING"),
        ("orphan", "EXECUTING", "EXECUTING"),
        ("no-begin", "EXECUTING", "EXECUTING"),
        ("unknown", "UNKNOWN_RESULT", "UNKNOWN_RESULT"),
        ("recovery-owned", "UNKNOWN_RESULT", "UNKNOWN_RESULT"),
        ("verification", "SUCCEEDED", "EXECUTED"),
        ("verified", "SUCCEEDED", "EXECUTED"),
    )
    for started_at_ms, (suffix, attempt_status, action_status) in enumerate(phases, start=1):
        connection.execute("INSERT INTO runs VALUES (?, 'WAITING_APPROVAL')", (f"run-{suffix}",))
        connection.execute(
            "INSERT INTO plans VALUES (?, ?, 1, 'WAITING_APPROVAL')",
            (f"plan-{suffix}", f"run-{suffix}"),
        )
        connection.execute(
            "INSERT INTO actions VALUES (?, ?, ?)",
            (f"action-{suffix}", f"plan-{suffix}", action_status),
        )
        connection.execute(
            "INSERT INTO approvals VALUES (?, ?)",
            (f"approval-{suffix}", f"action-{suffix}"),
        )
        connection.execute(
            "INSERT INTO execution_attempts VALUES (?, ?, ?, ?)",
            (
                f"attempt-{suffix}",
                f"approval-{suffix}",
                attempt_status,
                started_at_ms,
            ),
        )
    connection.execute(
        "INSERT INTO command_receipts VALUES "
        "('begin-orphan', 'BeginExecutionAttempt', 'ExecutionAttempt', "
        "'attempt-orphan', 'APPLIED', 'TRANSITION_APPLIED')"
    )
    connection.execute(
        "INSERT INTO recovery_contexts VALUES "
        "('run-recovery-owned', 'UNKNOWN_RESULT', 'action-recovery-owned', "
        "'attempt-recovery-owned')"
    )
    connection.execute("INSERT INTO verifications VALUES ('attempt-verified')")

    candidates = repository.list_reconciliation_candidates(10)

    assert [(candidate.execution_attempt_id, candidate.kind) for candidate in candidates] == [
        ("attempt-pre-begin", "PRE_BEGIN_ORPHAN"),
        ("attempt-orphan", "POST_BEGIN_ORPHAN"),
        ("attempt-unknown", "UNKNOWN_RESULT_UNRESOLVED"),
        ("attempt-verification", "EXECUTED_AWAITING_VERIFICATION"),
    ]


def test_reconciliation_candidates_exclude_stale_parent_authority_and_are_sql_bounded() -> None:
    connection = _reconciliation_connection()
    repository = SqliteExecutionAttemptRepository(connection)

    _seed_failed_attempt(
        connection,
        suffix="stale",
        run_status="WAITING_APPROVAL",
        plan_status="SUPERSEDED",
    )
    connection.execute("INSERT INTO actions VALUES ('action-stale-next', 'plan-stale', 'APPROVED')")
    connection.execute("INSERT INTO plans VALUES ('plan-stale-current', 'run-stale', 2, 'DRAFT')")

    _seed_failed_attempt(
        connection,
        suffix="terminal",
        run_status="CANCELLED",
        started_at_ms=2,
    )
    connection.execute(
        "INSERT INTO command_receipts VALUES "
        "('cancel-run-terminal', 'RequestRunCancellation', 'Run', 'run-terminal', "
        "'APPLIED', 'TRANSITION_APPLIED')"
    )

    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    assert repository.list_reconciliation_candidates(1) == ()

    candidate_select = next(
        statement for statement in statements if "WITH classified AS" in statement
    )
    assert "LIMIT 1" in candidate_select
