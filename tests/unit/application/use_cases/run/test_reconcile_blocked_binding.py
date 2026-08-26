from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.reconcile_blocked_binding import (
    ReconcileBlockedBindingCommand,
    ReconcileBlockedBindingHandler,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.require_recovery import (
    RequireRecoveryCommand,
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionHandler,
)
from google_work_agent.domain.canonical import calculate_canonical_json_hash
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)

_UnitOfWorkFactory = Callable[[], UnitOfWork]


class _ExecutionPort:
    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1:
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    def begin_shutdown(self) -> None: ...
    def await_drained(self, deadline_ms: int) -> bool:
        return True


def _handler(factory: _UnitOfWorkFactory) -> ReconcileBlockedBindingHandler:
    require_recovery = RequireRecoveryHandler(unit_of_work_factory=factory, now_ms=lambda: 20)
    return ReconcileBlockedBindingHandler(
        unit_of_work_factory=factory, require_recovery=require_recovery
    )


def test_a_first_pass_invokes_require_recovery_exactly_once_and_settles(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")

    result = _handler(factory)(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert result.outcome == "RECOVERED"
    assert _count(database_path, "command_receipts") == 1
    assert _count(database_path, "recovery_contexts") == 1
    assert _run_status(database_path, "r-1") == "RECOVERY_REQUIRED"
    assert _handoff_status(database_path, "h-1") == "SUPERSEDED"


def test_b_crash_after_context_committed_before_superseded_completes_without_remutating(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    handoff = _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")
    require_recovery = RequireRecoveryHandler(unit_of_work_factory=factory, now_ms=lambda: 20)
    _seed_pre_recovery(require_recovery, handoff)
    assert _run_status(database_path, "r-1") == "RECOVERY_REQUIRED"
    assert _handoff_status(database_path, "h-1") == "BLOCKED_BINDING"

    handler = ReconcileBlockedBindingHandler(
        unit_of_work_factory=factory, require_recovery=require_recovery
    )
    result = handler(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert result.outcome == "RECOVERED"
    assert _count(database_path, "command_receipts") == 1
    assert _count(database_path, "recovery_contexts") == 1
    assert _handoff_status(database_path, "h-1") == "SUPERSEDED"


def test_c_repeated_reconciliation_passes_produce_exactly_one_transition(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")
    handler = _handler(factory)

    first = handler(ReconcileBlockedBindingCommand(handoff_id="h-1"))
    second = handler(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert first.outcome == "RECOVERED"
    assert second.outcome == "NOT_FOUND"
    assert _count(database_path, "command_receipts") == 1
    assert _count(database_path, "recovery_contexts") == 1
    with factory() as unit_of_work:
        run = unit_of_work.runs.get_by_id("r-1")
    assert run is not None
    assert run.version == 1


def test_d_live_redrive_pass_reaches_recovery_required_without_restart(tmp_path: Path) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory, workflow_execution=_ExecutionPort(), id_factory=lambda: "a-1"
    )
    redrive = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=factory,
        schedule_run_execution=schedule,
        reconcile_blocked_binding=_handler(factory),
    )

    result = redrive(RedriveWorkflowHandoffsCommand(limit=10))

    assert result.blocked_binding == 1
    assert _run_status(database_path, "r-1") == "RECOVERY_REQUIRED"
    assert _handoff_status(database_path, "h-1") == "SUPERSEDED"


def test_e_terminal_run_supersedes_stale_handoff_without_creating_a_false_recovery(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="COMPLETED")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")

    result = _handler(factory)(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert result.outcome == "RUN_NOT_EXECUTABLE"
    assert _count(database_path, "command_receipts") == 0
    assert _count(database_path, "recovery_contexts") == 0
    assert _handoff_status(database_path, "h-1") == "SUPERSEDED"


def test_e_preempting_run_status_leaves_handoff_blocked_without_creating_a_false_recovery(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="CANCEL_REQUESTED")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")

    result = _handler(factory)(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert result.outcome == "PREEMPTED_BY_OTHER_AUTHORITY"
    assert _count(database_path, "command_receipts") == 0
    assert _count(database_path, "recovery_contexts") == 0
    assert _handoff_status(database_path, "h-1") == "BLOCKED_BINDING"


def test_f_non_matching_recovery_context_fails_closed_without_superseding(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")
    require_recovery = RequireRecoveryHandler(unit_of_work_factory=factory, now_ms=lambda: 20)
    unrelated = require_recovery(
        RequireRecoveryCommand(
            run_id="r-1",
            expected_version=0,
            command_id="system:action-recovery:unrelated-1",
            request_hash=calculate_canonical_json_hash({"unrelated": True}),
            reason="UNKNOWN_RESULT",
            scope="RUN",
            recovery_fingerprint="unrelated-fingerprint",
        )
    )
    assert unrelated.applied

    handler = ReconcileBlockedBindingHandler(
        unit_of_work_factory=factory, require_recovery=require_recovery
    )
    result = handler(ReconcileBlockedBindingCommand(handoff_id="h-1"))

    assert result.outcome == "NOT_MATCHING_RECOVERY_CONTEXT"
    assert _handoff_status(database_path, "h-1") == "BLOCKED_BINDING"
    with factory() as unit_of_work:
        context = unit_of_work.recovery_contexts.load_current_context("r-1")
    assert context is not None
    assert context["reason"] == "UNKNOWN_RESULT"


def test_g_later_handoff_cannot_bypass_the_blocked_head_before_settlement(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path, run_status="ANALYZING")
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    _stage_blocked_binding(factory, database_path, "h-1", "cmd-1")
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_pending_stage("h-2", "cmd-2"))
        unit_of_work.commit()
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory, workflow_execution=_ExecutionPort(), id_factory=lambda: "a-1"
    )

    redrive_without_reconciliation = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=factory, schedule_run_execution=schedule
    )
    blocked_pass = redrive_without_reconciliation(RedriveWorkflowHandoffsCommand(limit=10))

    assert blocked_pass.accepted == 0
    assert _handoff_status(database_path, "h-2") == "PENDING"

    redrive_with_reconciliation = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=factory,
        schedule_run_execution=schedule,
        reconcile_blocked_binding=_handler(factory),
    )
    settled_pass = redrive_with_reconciliation(RedriveWorkflowHandoffsCommand(limit=10))

    assert _handoff_status(database_path, "h-1") == "SUPERSEDED"
    assert settled_pass.accepted == 1
    assert _handoff_status(database_path, "h-2") == "DISPATCHED"


def _seed_pre_recovery(
    require_recovery: RequireRecoveryHandler, handoff: WorkflowHandoffV1
) -> str:
    resume_target = handoff.execution.resume_target
    fingerprint = calculate_canonical_json_hash(
        {
            "handoff_id": handoff.handoff_id,
            "run_id": handoff.execution.run_id,
            "langgraph_thread_id": handoff.execution.langgraph_thread_id,
            "graph_profile": handoff.execution.graph_profile,
            "graph_version": handoff.execution.graph_version,
            "checkpoint_id": handoff.checkpoint_id,
            "checkpoint_generation": handoff.checkpoint_generation,
            "resume_target": None if resume_target is None else asdict(resume_target),
        }
    )
    result = require_recovery(
        RequireRecoveryCommand(
            run_id=handoff.execution.run_id,
            expected_version=0,
            command_id=f"system:handoff-binding-recovery:{handoff.handoff_id}",
            request_hash=fingerprint,
            reason="CHECKPOINT_MISMATCH",
            scope="RUN",
            recovery_fingerprint=fingerprint,
            registered_resume_target=resume_target,
            contract_or_checkpoint_fingerprint=fingerprint,
        )
    )
    assert result.applied
    return fingerprint


def _stage_blocked_binding(
    factory: _UnitOfWorkFactory, database_path: Path, handoff_id: str, command_id: str
) -> WorkflowHandoffV1:
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(
            _pending_stage(handoff_id, command_id)
        )
        unit_of_work.commit()
    with connect_sqlite(database_path) as connection:
        connection.execute(
            "UPDATE workflow_handoffs SET status = 'BLOCKED_BINDING' WHERE handoff_id = ?;",
            (handoff_id,),
        )
        connection.commit()
    return handoff


def _pending_stage(handoff_id: str, command_id: str) -> WorkflowHandoffStageV1:
    return WorkflowHandoffStageV1(
        1,
        handoff_id,
        command_id,
        RunExecutionRefV1(1, "START", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None),
        None,
        0,
        "NONE",
        None,
        None,
    )


def _count(database_path: Path, table: str) -> int:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(f"SELECT COUNT(*) AS n FROM {table};").fetchone()
    return int(row["n"])


def _run_status(database_path: Path, run_id: str) -> str:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM runs WHERE id = ?;", (run_id,)
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _handoff_status(database_path: Path, handoff_id: str) -> str:
    with connect_sqlite(database_path) as connection:
        row = connection.execute(
            "SELECT status FROM workflow_handoffs WHERE handoff_id = ?;", (handoff_id,)
        ).fetchone()
    assert row is not None
    return str(row["status"])


def _database(tmp_path: Path, *, run_status: str) -> Path:
    path = tmp_path / "reconcile.db"
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
        connection.commit()
    return path
