from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.api.composition import drain_workflow_handoffs_to_quiescence
from google_work_agent.application.use_cases.recovery.require_recovery import (
    RequireRecoveryHandler,
)
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
    RedriveWorkflowHandoffsResult,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.persistence.unit_of_work import UnitOfWork
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
)

_UnitOfWorkFactory = Callable[[], UnitOfWork]


class _ExecutionPort:
    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1:
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    def begin_shutdown(self) -> None: ...
    def await_drained(self, deadline_ms: int) -> bool:
        return True


class _StubRedrive:
    def __init__(self, results: list[RedriveWorkflowHandoffsResult]) -> None:
        self._results = list(results)
        self.calls: list[int] = []

    def __call__(
        self, command: RedriveWorkflowHandoffsCommand | None = None
    ) -> RedriveWorkflowHandoffsResult:
        assert command is not None
        self.calls.append(command.limit)
        return self._results.pop(0)


def test_stops_immediately_when_first_pass_is_not_full() -> None:
    redrive = _StubRedrive(
        [RedriveWorkflowHandoffsResult(inspected=1, accepted=1, blocked_binding=0)]
    )

    passes = drain_workflow_handoffs_to_quiescence(redrive, batch_limit=10)  # type: ignore[arg-type]

    assert passes == 1
    assert redrive.calls == [10]


def test_continues_across_full_batches_while_progress_is_made() -> None:
    redrive = _StubRedrive(
        [
            RedriveWorkflowHandoffsResult(inspected=2, accepted=2, blocked_binding=0),
            RedriveWorkflowHandoffsResult(inspected=2, accepted=1, blocked_binding=0),
            RedriveWorkflowHandoffsResult(inspected=1, accepted=1, blocked_binding=0),
        ]
    )

    passes = drain_workflow_handoffs_to_quiescence(redrive, batch_limit=2)  # type: ignore[arg-type]

    assert passes == 3
    assert redrive.calls == [2, 2, 2]


def test_raises_rather_than_looping_forever_on_permanently_stuck_full_batches() -> None:
    """A batch that never shrinks below the limit (e.g. permanently fail-closed
    BLOCKED_BINDING rows) must not spin forever -- it terminates via the
    max_passes circuit breaker instead of hanging."""
    redrive = _StubRedrive(
        [
            RedriveWorkflowHandoffsResult(inspected=2, accepted=0, blocked_binding=2)
            for _ in range(3)
        ]
    )

    with pytest.raises(RuntimeError):
        drain_workflow_handoffs_to_quiescence(redrive, batch_limit=2, max_passes=3)  # type: ignore[arg-type]

    assert redrive.calls == [2, 2, 2]


def test_real_drain_processes_every_row_across_multiple_bounded_passes(
    tmp_path: Path,
) -> None:
    """Candidate rows exceed the configured batch limit: prove every batch stays
    bounded, no row starves, and the same RedriveWorkflowHandoffsHandler drains
    them all without an infinite no-progress loop."""
    database_path = _database(tmp_path, run_ids=["r-1", "r-2", "r-3", "r-4", "r-5"])
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    for index in range(1, 6):
        _stage_blocked_binding(factory, database_path, f"r-{index}", f"h-{index}", f"cmd-{index}")

    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory, workflow_execution=_ExecutionPort(), id_factory=lambda: "a-1"
    )
    require_recovery = RequireRecoveryHandler(unit_of_work_factory=factory, now_ms=lambda: 20)
    redrive = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=factory,
        schedule_run_execution=schedule,
        require_recovery=require_recovery,
    )

    passes = drain_workflow_handoffs_to_quiescence(redrive, batch_limit=2)

    assert passes == 3
    with connect_sqlite(database_path) as connection:
        remaining = connection.execute(
            "SELECT COUNT(*) AS n FROM workflow_handoffs WHERE status = 'BLOCKED_BINDING';"
        ).fetchone()
        superseded = connection.execute(
            "SELECT COUNT(*) AS n FROM workflow_handoffs WHERE status = 'SUPERSEDED';"
        ).fetchone()
    assert int(remaining["n"]) == 0
    assert int(superseded["n"]) == 5


def _stage_blocked_binding(
    factory: _UnitOfWorkFactory,
    database_path: Path,
    run_id: str,
    handoff_id: str,
    command_id: str,
) -> None:
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_stage(run_id, handoff_id, command_id))
        unit_of_work.commit()
    with connect_sqlite(database_path) as connection:
        connection.execute(
            "UPDATE workflow_handoffs SET status = 'BLOCKED_BINDING' WHERE handoff_id = ?;",
            (handoff_id,),
        )
        connection.commit()


def _stage(run_id: str, handoff_id: str, command_id: str) -> WorkflowHandoffStageV1:
    return WorkflowHandoffStageV1(
        1,
        handoff_id,
        command_id,
        RunExecutionRefV1(
            1, "START", run_id, f"t-{run_id}", "SIX_ROLE_BASELINE", "v1", "AUTO", None
        ),
        None,
        0,
        "NONE",
        None,
        None,
    )


def _database(tmp_path: Path, *, run_ids: list[str]) -> Path:
    path = tmp_path / "drain.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        for index, run_id in enumerate(run_ids):
            conversation_id = f"c-{index + 1}"
            connection.execute(
                "INSERT INTO conversations VALUES (?, 'a-1', 'Test', 1, 1);",
                (conversation_id,),
            )
            connection.execute(
                """
                INSERT INTO runs (
                    id, conversation_id, entry_mode, status, langgraph_thread_id,
                    requested_mode, actual_runtime, budget_json, version, started_at_ms,
                    finished_at_ms
                ) VALUES (?, ?, 'AGENT_SEARCH', 'ANALYZING', ?, 'AUTO', NULL, '{}', 0, 1, NULL);
                """,
                (run_id, conversation_id, f"t-{run_id}"),
            )
        connection.commit()
    return path
