from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from google_work_agent.application.use_cases.action.approve_action import (
    ApproveActionCommand,
    ApproveActionHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
)
from google_work_agent.domain.results import ResultCode
from google_work_agent.ports.persistence.audit_event_repository import AuditEventCursor
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    RunExecutionAcceptedV1,
)
from tests.support.fakes import DeterministicUUID


def _seed(database_path: Path, *, status: str = "PROPOSED") -> None:
    with connect_sqlite(database_path) as connection:
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
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, review_status,
                review_version, review_disposition, created_at_ms
            ) VALUES (
                'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 'PASSED', 1, 'PASS', 1
            );
            """
        )
        connection.execute(
            """
            INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                version, arguments_json, arguments_hash, expected_json,
                created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1,
                      'gmail_create_draft', 'CREATE', 'REQUIRED', 'GET_COMPARE',
                      'RESOURCE_SEARCH', ?, 1, '{}', ?, '{}', 1, 1);
            """,
            (status, "a" * 64),
        )


class _CheckpointFacts:
    def load_workflow_binding(self, _run_id: str) -> SimpleNamespace:
        return SimpleNamespace(
            langgraph_thread_id="thread-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
        )

    def load_same_run_checkpoint(self, _run_id: str, _thread_id: str) -> SimpleNamespace:
        return SimpleNamespace(checkpoint_id="checkpoint-1", checkpoint_generation=1)


class _ApproveUnitOfWork(SqliteUnitOfWork):
    def __enter__(self) -> SqliteUnitOfWork:
        entered = super().__enter__()
        entered.checkpoints = _CheckpointFacts()  # type: ignore[assignment]
        return entered


class _FailingInsertProxy:
    def __init__(self, target: object) -> None:
        self._target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    def insert_active_snapshot(self, _value: object) -> None:
        raise RuntimeError("injected approval failure")


class _FailingAppendProxy:
    def __init__(self, target: object) -> None:
        self._target = target

    def __getattr__(self, name: str) -> Any:
        return getattr(self._target, name)

    def append(self, _value: object) -> None:
        raise RuntimeError("injected audit failure")


class _FailingApprovalUnitOfWork(_ApproveUnitOfWork):
    def __enter__(self) -> SqliteUnitOfWork:
        entered = super().__enter__()
        entered.approvals = _FailingInsertProxy(entered.approvals)  # type: ignore[assignment]
        return entered


class _FailingAuditUnitOfWork(_ApproveUnitOfWork):
    def __enter__(self) -> SqliteUnitOfWork:
        entered = super().__enter__()
        entered.audits = _FailingAppendProxy(entered.audits)  # type: ignore[assignment]
        return entered


def _command(*, request_hash: str = "b" * 64) -> ApproveActionCommand:
    return ApproveActionCommand(
        command_id="approve-1",
        request_hash=request_hash,
        request_id="request-1",
        action_id="action-1",
        expected_version=1,
    )


def _handler(
    database_path: Path,
    *,
    uow_type: type[SqliteUnitOfWork] = _ApproveUnitOfWork,
    scheduled: list[str] | None = None,
) -> ApproveActionHandler:
    scheduled = scheduled if scheduled is not None else []

    def schedule(command: ScheduleRunExecutionCommand) -> RunExecutionAcceptedV1:
        handoff_id = command.handoff_id
        with connect_sqlite(database_path) as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM workflow_handoffs WHERE handoff_id=?;", (handoff_id,)
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM approvals WHERE action_id='action-1' AND status='ACTIVE';"
                ).fetchone()[0]
                == 1
            )
        scheduled.append(handoff_id)
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    return ApproveActionHandler(
        get_approval_ttl_minutes=lambda: 30,
        unit_of_work_factory=cast(Callable[[], UnitOfWork], lambda: uow_type(database_path)),
        now_ms=lambda: 1000,
        id_generator=DeterministicUUID(
            queued_ids=("approval-1", "handoff-1"), require_queued_ids=True
        ),
        resume_target_registry=SimpleNamespace(
            issue_main_stage=lambda profile, stage, version: MainControlResumeTargetV2(
                "MAIN_CONTROL", stage, profile, version
            )
        ),
        schedule_run_execution=schedule,
    )


@pytest.mark.parametrize("starting_status", ("PROPOSED", "MODIFIED"))
def test_approve_action_is_atomic_durable_replayable_and_uuid_backed(
    tmp_path: Path, starting_status: str
) -> None:
    database_path = tmp_path / f"approve-{starting_status.lower()}.db"
    _seed(database_path, status=starting_status)
    scheduled: list[str] = []
    handler = _handler(database_path, scheduled=scheduled)

    first = handler(_command())
    replay = handler(_command())
    mismatch = handler(_command(request_hash="c" * 64))

    assert first.applied is True and first.action_status == "APPROVED"
    assert replay == first
    assert mismatch.applied is False
    assert mismatch.result_code == ResultCode.DUPLICATE_COMMAND.value
    assert scheduled == ["handoff-1", "handoff-1"]
    with _ApproveUnitOfWork(database_path) as unit_of_work:
        action = unit_of_work.actions.get("action-1")
        approval = unit_of_work.approvals.get_active_for_action("action-1")
        receipt = unit_of_work.command_receipts.get_by_command_id("approve-1")
        handoff = unit_of_work.workflow_handoffs.get_by_trigger_command_id("approve-1")
        audits = unit_of_work.audits.list_page(AuditEventCursor(run_id="run-1"), 100)
    assert action is not None and action.status == "APPROVED" and action.version == 2
    assert approval is not None and approval.id == "approval-1"
    assert receipt is not None and receipt.status.value == "APPLIED"
    assert handoff is not None and handoff.handoff_id == "handoff-1"
    assert [event.event_type for event in audits].count("ACTION_APPROVED") == 1


@pytest.mark.parametrize("uow_type", (_FailingApprovalUnitOfWork, _FailingAuditUnitOfWork))
def test_approve_action_required_effect_failure_rolls_back_all_command_facts(
    tmp_path: Path, uow_type: type[SqliteUnitOfWork]
) -> None:
    database_path = tmp_path / f"approve-rollback-{uow_type.__name__}.db"
    _seed(database_path)

    with pytest.raises(RuntimeError, match="injected"):
        _handler(database_path, uow_type=uow_type)(_command())

    with connect_sqlite(database_path) as connection:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM actions WHERE id='action-1'),
                (SELECT version FROM actions WHERE id='action-1'),
                (SELECT COUNT(*) FROM approvals),
                (SELECT COUNT(*) FROM command_receipts),
                (SELECT COUNT(*) FROM audit_events),
                (SELECT COUNT(*) FROM workflow_handoffs);
            """
        ).fetchone()
    assert tuple(facts) == ("PROPOSED", 1, 0, 0, 0, 0)
