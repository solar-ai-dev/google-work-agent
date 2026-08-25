from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.redrive_workflow_handoffs import (
    RedriveWorkflowHandoffsCommand,
    RedriveWorkflowHandoffsHandler,
)
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
)


class _ExecutionPort:
    def __init__(self) -> None:
        self.submitted: list[str] = []

    def submit(self, submission: WorkflowExecutionSubmissionV2) -> RunExecutionAcceptedV1:
        self.submitted.append(submission.admission.handoff_id)
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    def begin_shutdown(self) -> None: ...
    def await_drained(self, deadline_ms: int) -> bool:
        return True


def test_redrive_uses_schedule_handler_for_only_the_same_run_dispatch_head(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        unit_of_work.workflow_handoffs.stage_pending(_stage("h-2", "cmd-2"))
        unit_of_work.commit()
    execution = _ExecutionPort()
    schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=execution,
        id_factory=lambda: "admission-1",
    )
    handler = RedriveWorkflowHandoffsHandler(
        unit_of_work_factory=factory,
        schedule_run_execution=schedule,
    )

    result = handler(RedriveWorkflowHandoffsCommand(limit=10))

    assert result.inspected == 2
    assert result.accepted == 1
    assert execution.submitted == ["h-1"]


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "redrive.db"
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
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """
        )
        connection.commit()
    return path


def _stage(handoff_id: str, command_id: str) -> WorkflowHandoffStageV1:
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
