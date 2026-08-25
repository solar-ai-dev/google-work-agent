from __future__ import annotations

from pathlib import Path
from threading import Event

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionRefV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
)


class _AcceptedThenCrash:
    def __init__(self) -> None:
        self.submission: WorkflowExecutionSubmissionV2 | None = None

    def submit(self, submission: WorkflowExecutionSubmissionV2):
        from google_work_agent.ports.system.contracts.workflow_handoff import RunExecutionAcceptedV1

        self.submission = submission
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    def begin_shutdown(self) -> None: ...
    def await_drained(self, deadline_ms: int) -> bool:
        return False


def test_persisted_admission_survives_acceptance_crash_and_settles_before_owner_io(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                1,
                "h-1",
                "cmd-1",
                RunExecutionRefV1(
                    1, "START", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None
                ),
                None,
                0,
                "NONE",
                None,
                None,
            )
        )
        unit_of_work.commit()
    crashed = _AcceptedThenCrash()
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=crashed,
        id_factory=lambda: "admission-1",
    )
    assert schedule(ScheduleRunExecutionCommand("h-1")).accepted
    assert crashed.submission is not None

    owner_io = Event()

    def recovered_worker(admission) -> None:
        with factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(admission.handoff_id)
            assert handoff is not None
            settlement = unit_of_work.workflow_handoffs.mark_consumed_and_clear_payload(
                handoff.handoff_id, handoff.version, admission.admission_id, "cp-1", 1
            )
            unit_of_work.commit()
        if settlement.outcome == "SETTLED":
            owner_io.set()

    restarted = BackgroundRunExecutorAdapter(execute_admission=recovered_worker)
    try:
        assert restarted.submit(crashed.submission).accepted
        assert owner_io.wait(1)
        assert restarted.await_drained(1000)
    finally:
        restarted.close()
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "CONSUMED"


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "crash.db"
    with connect_sqlite(path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs VALUES (
                'r-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-1',
                'AUTO', NULL, '{}', 0, 1, NULL
            );
            """
        )
        connection.commit()
    return path
