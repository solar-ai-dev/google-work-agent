from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.run.begin_planning import (
    BeginPlanningCommand,
    BeginPlanningHandler,
)
from google_work_agent.domain.run.model import RunStatusV1
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_binding import GraphProfileIdV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    MainControlResumeTargetV2,
    MainResumeStageIdV1,
    RegisteredResumeTargetRefV2,
)


class _ResumeTargetRegistry:
    def issue_main_stage(
        self,
        graph_profile: GraphProfileIdV1,
        stage_id: MainResumeStageIdV1,
        graph_version: str,
    ) -> MainControlResumeTargetV2:
        return MainControlResumeTargetV2(
            kind="MAIN_CONTROL",
            stage_id=stage_id,
            graph_profile=graph_profile,
            graph_version=graph_version,
        )

    def validate(self, ref: RegisteredResumeTargetRefV2) -> None:
        del ref


class _FailValidatedRunCas:
    def __init__(self, delegate: Any) -> None:
        self._delegate = delegate
        self.attempted = False

    def get(self, run_id: str) -> object:
        return self._delegate.get(run_id)

    def update_if_version_and_status(self, *_args: object, **_kwargs: object) -> bool:
        self.attempted = True
        return False


class _RunCasFailureUnitOfWork:
    def __init__(self, database_path: Path) -> None:
        self._delegate = SqliteUnitOfWork(database_path, now_ms=lambda: 20)
        self.runs: _FailValidatedRunCas | None = None

    def __enter__(self) -> UnitOfWork:
        delegate = self._delegate.__enter__()
        self.runs = _FailValidatedRunCas(delegate.runs)
        return cast(UnitOfWork, self)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        self._delegate.__exit__(exc_type, exc, exc_tb)

    def __getattr__(self, name: str) -> object:
        return getattr(self._delegate, name)


def _database(tmp_path: Path, source_status: RunStatusV1) -> Path:
    path = tmp_path / f"begin-planning-{source_status.value.lower()}.sqlite3"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """INSERT INTO runs (
                   id, conversation_id, entry_mode, status, langgraph_thread_id,
                   requested_mode, actual_runtime, budget_json, version,
                   started_at_ms, finished_at_ms
               ) VALUES (
                   'run-1', 'conversation-1', 'AGENT_SEARCH', ?, 'thread-1',
                   'AUTO', NULL, '{}', 4, 1, NULL
               );""",
            (source_status.value,),
        )
        connection.execute(
            """INSERT INTO plans (
                   id, run_id, revision_no, status, summary_text, created_at_ms,
                   review_status, review_version, review_disposition
               ) VALUES (
                   'plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                   'REVISE', 3, 'REVISE'
               );"""
        )
        connection.execute(
            """INSERT INTO actions (
                   id, plan_id, connector_id, position, tool_name, effect_type,
                   approval_requirement, verification_policy, recovery_policy,
                   target_resource_ref_id, status, arguments_json, arguments_hash,
                   expected_json, risk_json, version, created_at_ms, updated_at_ms
               ) VALUES (
                   'action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                   'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', NULL,
                   'APPROVED', '{}', ?, '{}', '{}', 1, 2, 2
               );""",
            ("a" * 64,),
        )
        connection.execute(
            """INSERT INTO approvals (
                   id, action_id, approval_no, action_version, status,
                   approved_by_account_id, approved_by_display,
                   arguments_snapshot_json, canonical_arguments_hash,
                   source_snapshot_json, source_snapshot_hash, policy_version,
                   tool_schema_version, idempotency_key, recovery_fingerprint,
                   approved_at_ms, expires_at_ms, consumed_at_ms
               ) VALUES (
                   'approval-1', 'action-1', 1, 1, 'ACTIVE', 'account-1', NULL,
                   '{}', ?, '{}', ?, 'v1', 'v1', ?, ?, 2, 1000, NULL
               );""",
            ("a" * 64, "b" * 64, "c" * 64, "d" * 64),
        )
        connection.commit()
    return path


def _handler(unit_of_work_factory: Any) -> BeginPlanningHandler:
    return BeginPlanningHandler(
        unit_of_work_factory=unit_of_work_factory,
        now_ms=lambda: 20,
        id_factory=lambda: "unused-handoff",
        resume_target_registry=_ResumeTargetRegistry(),
    )


def _command() -> BeginPlanningCommand:
    return BeginPlanningCommand(
        run_id="run-1",
        expected_version=4,
        command_id="begin-planning-1",
        request_hash="e" * 64,
        plan_id="plan-1",
        expected_review_version=3,
    )


def _durable_snapshot(path: Path) -> dict[str, object]:
    with connect_sqlite(path) as connection:
        run = connection.execute(
            "SELECT status, version FROM runs WHERE id='run-1';"
        ).fetchone()
        plan = connection.execute(
            "SELECT status FROM plans WHERE id='plan-1';"
        ).fetchone()
        action = connection.execute(
            "SELECT status, version FROM actions WHERE id='action-1';"
        ).fetchone()
        approval = connection.execute(
            "SELECT status FROM approvals WHERE id='approval-1';"
        ).fetchone()
        counts = {
            table: int(
                connection.execute(
                    f"SELECT COUNT(*) AS count FROM {table} WHERE "
                    + (
                        "aggregate_id='run-1'"
                        if table == "command_receipts"
                        else "run_id='run-1'"
                    )
                ).fetchone()["count"]
            )
            for table in ("command_receipts", "audit_events", "workflow_handoffs")
        }
    return {
        "run": tuple(run),
        "plan": plan["status"],
        "action": tuple(action),
        "approval": approval["status"],
        **counts,
    }


@pytest.mark.parametrize(
    "source_status",
    (RunStatusV1.WAITING_APPROVAL, RunStatusV1.VERIFYING),
)
def test_begin_planning__published_plan_reentry__is_child_first_and_atomic(
    tmp_path: Path,
    source_status: RunStatusV1,
) -> None:
    path = _database(tmp_path, source_status)

    result = _handler(sqlite_unit_of_work_factory(path, now_ms=lambda: 20))(_command())

    assert result.applied
    snapshot = _durable_snapshot(path)
    assert snapshot == {
        "run": ("PLANNING", 5),
        "plan": "SUPERSEDED",
        "action": ("APPROVED", 1),
        "approval": "REVOKED",
        "command_receipts": 1,
        "audit_events": 1,
        "workflow_handoffs": 0,
    }


def test_begin_planning__validated_run_cas_failure__rolls_back_entire_uow(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path, RunStatusV1.WAITING_APPROVAL)
    original = _durable_snapshot(path)
    unit_of_work = _RunCasFailureUnitOfWork(path)

    with pytest.raises(RuntimeError, match="validated Run planning CAS failed"):
        _handler(lambda: cast(UnitOfWork, unit_of_work))(_command())

    assert unit_of_work.runs is not None and unit_of_work.runs.attempted
    assert _durable_snapshot(path) == original == {
        "run": ("WAITING_APPROVAL", 4),
        "plan": "WAITING_APPROVAL",
        "action": ("APPROVED", 1),
        "approval": "ACTIVE",
        "command_receipts": 0,
        "audit_events": 0,
        "workflow_handoffs": 0,
    }
