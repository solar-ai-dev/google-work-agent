"""Durable safety closure tests for canonical ClaimExecution."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from google_work_agent.adapters.persistence import connect_sqlite, sqlite_unit_of_work_factory
from google_work_agent.adapters.persistence.sqlite.repositories.audit_event_repository import (
    SqliteAuditEventRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.command_receipt_repository import (
    SqliteCommandReceiptRepository,
)
from google_work_agent.adapters.persistence.sqlite.repositories.execution_attempt_repository import (  # noqa: E501
    SqliteExecutionAttemptRepository,
)
from google_work_agent.application.use_cases.action.write_approval_contracts import (
    ApproveWriteActionCommand,
)
from google_work_agent.application.use_cases.claim.build_claim_context import (
    BuildClaimContextHandler,
    BuildClaimContextQueryV1,
)
from google_work_agent.application.use_cases.claim.claim_execution import (
    ClaimExecutionCommand,
    ClaimExecutionHandler,
)
from google_work_agent.domain.action.model import ActionStatusV1
from google_work_agent.domain.execution_attempt.model import ExecutionAttemptStatusV1
from google_work_agent.domain.results import ResultCode
from tests.integration.persistence.test_write_actions import (
    FakeClockPort,
    FakeGoogleGateway,
    _prepare_write_plan,
)
from tests.support.legacy_write_approval import ApproveWriteActionService

pytest_plugins = ("tests.integration.persistence.test_write_actions",)

SERVICE_INSTANCE_ID = "c2-write-svc-1"


def _approve(*, write_database: Path, clock: FakeClockPort, suffix: str) -> None:
    _prepare_write_plan(write_database=write_database, clock=clock, suffix=suffix)
    approved = ApproveWriteActionService(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )(
        ApproveWriteActionCommand(
            command_id=f"approve-{suffix}",
            request_hash="a1" * 32,
            action_id=f"action-{suffix}",
            expected_version=0,
            approved_by_account_id="account-1",
            approved_by_display="User",
            source_snapshot={},
            approval_id=f"approval-{suffix}",
            idempotency_key=(f"approval-{suffix}".encode().hex())[:64].ljust(64, "0"),
        )
    )
    assert approved.applied is True
    assert approved.action_status == ActionStatusV1.APPROVED.value


def _handler(write_database: Path, clock: FakeClockPort) -> ClaimExecutionHandler:
    return ClaimExecutionHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
    )


def _command(
    suffix: str,
    *,
    request_hash: str = "b1" * 32,
    expected_version: int = 1,
) -> ClaimExecutionCommand:
    return ClaimExecutionCommand(
        command_id=f"claim-{suffix}",
        request_hash=request_hash,
        action_id=f"action-{suffix}",
        expected_version=expected_version,
        source_snapshot={},
        attempt_id=f"attempt-{suffix}",
    )


def _claim_snapshot(write_database: Path, suffix: str) -> tuple[object, ...]:
    connection = connect_sqlite(write_database)
    try:
        row = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id = ?),
                (SELECT version FROM actions WHERE id = ?),
                (SELECT status FROM approvals WHERE id = ?),
                (SELECT consumed_at_ms FROM approvals WHERE id = ?),
                (SELECT status FROM execution_attempts WHERE id = ?),
                (SELECT COUNT(*) FROM execution_attempts WHERE approval_id = ?),
                (SELECT status FROM command_receipts WHERE command_id = ?),
                (SELECT COUNT(*) FROM trace_events
                    WHERE action_id = ? AND event_type = 'EXECUTION_CLAIMED'),
                (SELECT COUNT(*) FROM audit_events
                    WHERE action_id = ? AND event_type = 'APPROVAL_CONSUMED'),
                (SELECT COUNT(*) FROM audit_events
                    WHERE action_id = ? AND event_type = 'EXECUTION_CLAIMED');
            """,
            (
                f"action-{suffix}",
                f"action-{suffix}",
                f"approval-{suffix}",
                f"approval-{suffix}",
                f"attempt-{suffix}",
                f"approval-{suffix}",
                f"claim-{suffix}",
                f"action-{suffix}",
                f"action-{suffix}",
                f"action-{suffix}",
            ),
        ).fetchone()
        return tuple(row)
    finally:
        connection.close()


def test_valid_claim_is_one_atomic_commit_and_replay_is_single_use(
    write_database: Path,
    fixture_gateway: FakeGoogleGateway,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "c2-happy"
    _approve(write_database=write_database, clock=clock, suffix=suffix)
    handler = _handler(write_database, clock)
    command = _command(suffix)

    first = handler(command)
    second = handler(command)

    assert first.applied is True
    assert first.result_code is ResultCode.TRANSITION_APPLIED
    assert first.current_status is ActionStatusV1.EXECUTING
    assert first.current_version == 2
    assert first.approval_id == f"approval-{suffix}"
    assert first.attempt_id == f"attempt-{suffix}"
    assert second == first
    assert fixture_gateway.call_log == []
    with sqlite_unit_of_work_factory(write_database)() as unit_of_work:
        claimed_action = unit_of_work.actions.get(f"action-{suffix}")
    assert claimed_action is not None
    signed_payloads: list[dict[str, object]] = []
    context = BuildClaimContextHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(write_database),
        now_ms=clock.now_ms,
        id_factory=lambda: f"nonce-{suffix}",
        sign_claim_context=lambda payload: signed_payloads.append(payload) or "signature",
    )(
        BuildClaimContextQueryV1(
            schema_version=1,
            action_id=f"action-{suffix}",
            approval_id=f"approval-{suffix}",
            execution_attempt_id=f"attempt-{suffix}",
            tool_name="tasks_create_task",
            approval_arguments_hash=claimed_action.arguments_hash,
            final_tool_arguments={"payload": {"title": "Task"}},
            service_instance_id=SERVICE_INSTANCE_ID,
            mcp_process_instance_id="mcp-process-1",
        )
    )
    assert context.action_id == f"action-{suffix}"
    assert context.approval_id == f"approval-{suffix}"
    assert context.execution_attempt_id == f"attempt-{suffix}"
    assert context.tool_name == "tasks_create_task"
    assert context.service_instance_id == SERVICE_INSTANCE_ID
    assert context.nonce == f"nonce-{suffix}"
    assert context.expires_at_ms > context.issued_at_ms
    assert signed_payloads[0]["execution_attempt_id"] == f"attempt-{suffix}"

    assert _claim_snapshot(write_database, suffix) == (
        "EXECUTING",
        2,
        "CONSUMED",
        1000,
        "CLAIMED",
        1,
        "APPLIED",
        1,
        1,
        1,
    )


def test_receipt_hash_mismatch_does_not_create_second_attempt(write_database: Path) -> None:
    clock = FakeClockPort(1000)
    suffix = "c2-replay"
    _approve(write_database=write_database, clock=clock, suffix=suffix)
    handler = _handler(write_database, clock)
    original = _command(suffix)
    assert handler(original).applied is True

    conflict = handler(replace(original, request_hash="ff" * 32))

    assert conflict.applied is False
    assert conflict.result_code is ResultCode.DUPLICATE_COMMAND
    connection = connect_sqlite(write_database)
    try:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_attempts WHERE approval_id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("kind", "expected_code", "detail"),
    (
        ("hash", ResultCode.STATE_CONFLICT, "source snapshot"),
        ("version", ResultCode.VERSION_CONFLICT, "expected_version"),
    ),
)
def test_hash_mismatch_and_stale_action_version_fail_closed(
    write_database: Path,
    kind: str,
    expected_code: ResultCode,
    detail: str,
) -> None:
    clock = FakeClockPort(1000)
    suffix = f"c2-{kind}"
    _approve(write_database=write_database, clock=clock, suffix=suffix)
    handler = _handler(write_database, clock)
    command = _command(suffix)
    if kind == "hash":
        command = replace(command, source_snapshot={"changed": True})
    else:
        command = replace(command, expected_version=0)

    result = handler(command)

    assert result.applied is False
    assert result.result_code is expected_code
    assert detail in (result.conflict_detail or "")
    connection = connect_sqlite(write_database)
    try:
        assert tuple(
            connection.execute(
                "SELECT status, version FROM actions WHERE id = ?;",
                (f"action-{suffix}",),
            ).fetchone()
        ) == ("APPROVED", 1)
        assert (
            connection.execute(
                "SELECT status FROM approvals WHERE id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()[0]
            == "ACTIVE"
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_attempts WHERE approval_id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()


def test_invalid_approval_is_rejected_without_attempt(write_database: Path) -> None:
    clock = FakeClockPort(1000)
    suffix = "c2-no-approval"
    _prepare_write_plan(write_database=write_database, clock=clock, suffix=suffix)

    result = _handler(write_database, clock)(_command(suffix, expected_version=0))

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert "ACTIVE approval" in (result.conflict_detail or "")
    connection = connect_sqlite(write_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM execution_attempts;").fetchone()[0] == 0
    finally:
        connection.close()


def test_active_attempt_guard_fails_before_mutation(
    write_database: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = FakeClockPort(1000)
    suffix = "c2-active-attempt"
    _approve(write_database=write_database, clock=clock, suffix=suffix)
    monkeypatch.setattr(
        SqliteExecutionAttemptRepository,
        "get_active_for_approval",
        lambda self, approval_id: SimpleNamespace(status=ExecutionAttemptStatusV1.CLAIMED),
    )

    result = _handler(write_database, clock)(_command(suffix))

    assert result.applied is False
    assert result.result_code is ResultCode.STATE_CONFLICT
    assert "active execution attempt" in (result.conflict_detail or "")
    connection = connect_sqlite(write_database)
    try:
        assert tuple(
            connection.execute(
                "SELECT status, version FROM actions WHERE id = ?;",
                (f"action-{suffix}",),
            ).fetchone()
        ) == ("APPROVED", 1)
        assert (
            connection.execute(
                "SELECT status FROM approvals WHERE id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()[0]
            == "ACTIVE"
        )
    finally:
        connection.close()


@pytest.mark.parametrize("failure_point", ("audit", "receipt"))
def test_transaction_failure_rolls_back_claim_children_and_observability(
    write_database: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: str,
) -> None:
    clock = FakeClockPort(1000)
    suffix = f"c2-rollback-{failure_point}"
    _approve(write_database=write_database, clock=clock, suffix=suffix)

    def fail(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise RuntimeError(f"injected {failure_point} failure")

    if failure_point == "audit":
        monkeypatch.setattr(SqliteAuditEventRepository, "append", fail)
    else:
        monkeypatch.setattr(SqliteCommandReceiptRepository, "store_result", fail)

    with pytest.raises(RuntimeError, match=f"injected {failure_point} failure"):
        _handler(write_database, clock)(_command(suffix))

    connection = connect_sqlite(write_database)
    try:
        assert tuple(
            connection.execute(
                "SELECT status, version FROM actions WHERE id = ?;",
                (f"action-{suffix}",),
            ).fetchone()
        ) == ("APPROVED", 1)
        assert tuple(
            connection.execute(
                "SELECT status, consumed_at_ms FROM approvals WHERE id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()
        ) == ("ACTIVE", None)
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM execution_attempts WHERE approval_id = ?;",
                (f"approval-{suffix}",),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM command_receipts WHERE command_id = ?;",
                (f"claim-{suffix}",),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM trace_events WHERE action_id = ? "
                "AND event_type = 'EXECUTION_CLAIMED';",
                (f"action-{suffix}",),
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM audit_events WHERE action_id = ? "
                "AND event_type IN ('APPROVAL_CONSUMED', 'EXECUTION_CLAIMED');",
                (f"action-{suffix}",),
            ).fetchone()[0]
            == 0
        )
    finally:
        connection.close()
