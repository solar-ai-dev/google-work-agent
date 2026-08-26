from __future__ import annotations

from pathlib import Path
from threading import Event
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.use_cases.run.schedule_run_execution import (
    CheckpointEffectiveBindingResolver,
    ScheduleRunExecutionCommand,
    ScheduleRunExecutionHandler,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
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

    checkpoint = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 10)
    graph = _graph(checkpoint)
    target = _target()

    def materialize(admission):
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id=admission.handoff_id,
            owner_scope="REQUEST_UNDERSTANDING",
            resume_target=target,
        ):
            graph.invoke(
                {"value": 0},
                config={"configurable": {"thread_id": "t-1"}},
                interrupt_before=["request_understanding"],
            )
        result = checkpoint.load_same_run_checkpoint("r-1", "t-1")
        assert result is not None
        return result

    def crash_after_descendant(admission, _handoff) -> None:
        initial = checkpoint.load_same_run_checkpoint("r-1", "t-1")
        assert initial is not None
        with factory() as unit_of_work:
            settled = unit_of_work.workflow_handoffs.get("h-1")
        assert settled is not None
        assert settled.status == "CONSUMED"
        assert settled.applied_checkpoint_id == initial.checkpoint_id
        with checkpoint.execution_scope(
            admission,
            applied_handoff_id=admission.handoff_id,
            owner_scope="REQUEST_UNDERSTANDING",
            resume_target=target,
        ):
            graph.invoke(
                None,
                config={"configurable": {"thread_id": "t-1"}},
                interrupt_before=["context_retriever"],
            )
        descendant = checkpoint.load_same_run_checkpoint("r-1", "t-1")
        assert descendant is not None
        assert descendant.checkpoint_generation > initial.checkpoint_generation
        assert descendant.active_handoff_id == "h-1"
        assert descendant.registered_resume_target is not None
        assert descendant.registered_resume_target.kind == "AGENT_NODE"
        assert descendant.registered_resume_target.semantic_owner_id == "RETRIEVAL"
        assert descendant.registered_resume_target.node_id == "retrieval.plan_query"
        raise RuntimeError("simulated crash after settlement")

    restarted = BackgroundRunExecutorAdapter(
        unit_of_work_factory=factory,
        checkpoint_port=checkpoint,
        materialize_admission_checkpoint=materialize,
        invoke_semantic_owner=crash_after_descendant,
        release_active_lineage=lambda run_id, thread_id, handoff_id, run_sequence: (
            checkpoint.release_active_lineage(
                run_id=run_id,
                thread_id=thread_id,
                handoff_id=handoff_id,
                run_sequence=run_sequence,
            )
        ),
    )
    try:
        assert restarted.submit(crashed.submission).accepted
        assert restarted.await_drained(1000)
    finally:
        restarted.close()
        checkpoint.close()
    with factory() as unit_of_work:
        persisted = unit_of_work.workflow_handoffs.get("h-1")
    assert persisted is not None
    assert persisted.status == "CONSUMED"

    reopened = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 20)
    latest = reopened.load_same_run_checkpoint("r-1", "t-1")
    assert latest is not None
    assert latest.active_handoff_id == "h-1"
    recovered_owner = Event()

    def recover(admission, _handoff) -> None:
        assert admission.effective_binding.checkpoint_id == latest.checkpoint_id
        assert admission.effective_binding.checkpoint_generation == latest.checkpoint_generation
        recovered_owner.set()

    recovery_worker = BackgroundRunExecutorAdapter(
        unit_of_work_factory=factory,
        checkpoint_port=reopened,
        materialize_admission_checkpoint=lambda _admission: (_ for _ in ()).throw(
            AssertionError("RESUME must reuse the native descendant checkpoint")
        ),
        invoke_semantic_owner=recover,
        release_active_lineage=lambda run_id, thread_id, handoff_id, run_sequence: (
            reopened.release_active_lineage(
                run_id=run_id,
                thread_id=thread_id,
                handoff_id=handoff_id,
                run_sequence=run_sequence,
            )
        ),
    )
    recovery_schedule = ScheduleRunExecutionHandler(
        unit_of_work_factory=factory,
        workflow_execution=recovery_worker,
        id_factory=lambda: "admission-2",
        effective_binding_resolver=CheckpointEffectiveBindingResolver(reopened),
    )
    try:
        accepted = recovery_schedule(
            ScheduleRunExecutionCommand("h-1", "CONSUMED_CONTINUATION_RECOVERY")
        )
        assert accepted.accepted
        assert recovered_owner.wait(1)
        assert recovery_worker.await_drained(1000)
    finally:
        recovery_worker.close()
        reopened.close()


class _GraphState(TypedDict):
    value: int


def _graph(checkpoint):
    builder = StateGraph(_GraphState)
    builder.add_node("request_understanding", lambda state: {"value": state["value"] + 1})
    builder.add_node("context_retriever", lambda state: {"value": state["value"] + 1})
    builder.add_edge(START, "request_understanding")
    builder.add_edge("request_understanding", "context_retriever")
    builder.add_edge("context_retriever", END)
    return builder.compile(checkpointer=checkpoint)


def _target() -> AgentNodeResumeTargetV2:
    return AgentNodeResumeTargetV2(
        "AGENT_NODE",
        "REQUEST_UNDERSTANDING",
        "SIX_REQUEST_UNDERSTANDING",
        "request.identify_goal",
        "SIX_ROLE_BASELINE",
        "v1",
    )


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
