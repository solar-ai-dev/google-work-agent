from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from threading import Event
from typing import TypedDict, cast

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.runtime.background_run_executor import (
    BackgroundRunExecutorAdapter,
)
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.ports.system.checkpoint_port import CheckpointPort
from google_work_agent.ports.system.contracts.checkpoint import GraphCheckpointEnvelopeV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    AgentNodeResumeTargetV2,
    RunExecutionRefV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowExecutionSubmissionV2,
    WorkflowHandoffStageV1,
    WorkflowHandoffV1,
)


def test_same_admission_replay__is_idempotently_accepted__without_second_worker_entry(
    tmp_path: Path,
) -> None:
    executed: list[str] = []
    completed = Event()

    def execute(admission: WorkflowExecutionAdmissionV1, _handoff: object) -> None:
        executed.append(admission.admission_id)
        completed.set()

    adapter, _, checkpoint = _adapter(tmp_path, execute)
    try:
        submission = WorkflowExecutionSubmissionV2(2, _admission("a-1", "r-1"))
        assert adapter.submit(submission).reason_code == "ACCEPTED"
        assert adapter.submit(submission).reason_code == "ACCEPTED"
        assert completed.wait(1)
        assert adapter.await_drained(1000)
        assert executed == ["a-1"]
    finally:
        adapter.close()
        checkpoint.close()


def test_different_admission__for_active_run__is_not_accepted(tmp_path: Path) -> None:
    release = Event()
    started = Event()

    def execute(admission: WorkflowExecutionAdmissionV1, _handoff: object) -> None:
        started.set()
        release.wait(1)

    adapter, _, checkpoint = _adapter(tmp_path, execute)
    try:
        assert adapter.submit(WorkflowExecutionSubmissionV2(2, _admission("a-1", "r-1"))).accepted
        assert started.wait(1)
        result = adapter.submit(WorkflowExecutionSubmissionV2(2, _admission("a-2", "r-1")))
        assert not result.accepted
        assert result.reason_code == "ALREADY_RUNNING"
    finally:
        release.set()
        adapter.close()
        checkpoint.close()


def test_failed_pre_settlement__admission_can_be__redriven_in_same_process(
    tmp_path: Path,
) -> None:
    executed = Event()
    adapter, _, checkpoint = _adapter(
        tmp_path,
        lambda _admission, _handoff: executed.set(),
        fail_materialize_once=True,
    )
    try:
        submission = WorkflowExecutionSubmissionV2(2, _admission("a-1", "r-1"))
        assert adapter.submit(submission).accepted
        assert adapter.await_drained(1000)
        assert not executed.is_set()

        assert adapter.submit(submission).accepted
        assert executed.wait(1)
        assert adapter.await_drained(1000)
    finally:
        adapter.close()
        checkpoint.close()


def test_stale_admission__is_retired_before__semantic_owner_io(tmp_path: Path) -> None:
    owner_io = Event()
    adapter, database_path, checkpoint = _adapter(
        tmp_path,
        lambda _admission, _handoff: owner_io.set(),
        stale_on_checkpoint_store=True,
    )
    try:
        admission = _admission("a-1", "r-1")
        assert adapter.submit(WorkflowExecutionSubmissionV2(2, admission)).accepted
        assert adapter.await_drained(1000)
        assert not owner_io.is_set()
        factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
        with factory() as unit_of_work:
            handoff = unit_of_work.workflow_handoffs.get(admission.handoff_id)
        assert handoff is not None
        assert handoff.status == "SUPERSEDED"
        assert handoff.execution_admission is None
        latest = checkpoint.load_same_run_checkpoint("r-1", "t-r-1")
        assert latest is not None
        assert latest.active_handoff_id is None
    finally:
        adapter.close()
        checkpoint.close()


def _admission(admission_id: str, run_id: str) -> WorkflowExecutionAdmissionV1:
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id=admission_id,
        handoff_id=f"h-{admission_id}",
        handoff_run_sequence=1,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id=run_id,
            langgraph_thread_id=f"t-{run_id}",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=0,
    )


def _adapter(
    tmp_path: Path,
    execute: Callable[[WorkflowExecutionAdmissionV1, WorkflowHandoffV1], None],
    *,
    stale_on_checkpoint_store: bool = False,
    fail_materialize_once: bool = False,
) -> tuple[BackgroundRunExecutorAdapter, Path, SqliteCheckpointAdapter]:
    database_path = tmp_path / "domain.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('a-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute("INSERT INTO conversations VALUES ('c-1', 'a-1', 'Test', 1, 1);")
        connection.execute(
            """
            INSERT INTO runs VALUES (
                'r-1', 'c-1', 'AGENT_SEARCH', 'CREATED', 't-r-1',
                'AUTO', NULL, '{}', 0, 1, NULL, NULL
            );
            """
        )
        connection.commit()
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    admission = _admission("a-1", "r-1")
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(
            WorkflowHandoffStageV1(
                1,
                admission.handoff_id,
                "cmd-1",
                RunExecutionRefV1(
                    1, "START", "r-1", "t-r-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None
                ),
                None,
                0,
                "NONE",
                None,
                None,
            )
        )
        unit_of_work.workflow_handoffs.claim_execution_admission(admission.handoff_id, 0, admission)
        unit_of_work.commit()
    checkpoint = SqliteCheckpointAdapter(tmp_path / "checkpoint.db", now_ms=lambda: 10)

    class _State(TypedDict):
        value: int

    graph_builder = StateGraph(_State)
    graph_builder.add_node("owner", lambda state: {"value": state["value"] + 1})
    graph_builder.add_edge(START, "owner")
    graph_builder.add_edge("owner", END)
    graph = graph_builder.compile(checkpointer=checkpoint)
    target = AgentNodeResumeTargetV2(
        "AGENT_NODE",
        "REQUEST_UNDERSTANDING",
        "SIX_REQUEST_UNDERSTANDING",
        "request.identify_goal",
        "SIX_ROLE_BASELINE",
        "v1",
    )

    materialize_failed = False

    def materialize(
        value: WorkflowExecutionAdmissionV1, _handoff: WorkflowHandoffV1
    ) -> GraphCheckpointEnvelopeV1:
        nonlocal materialize_failed
        if fail_materialize_once and not materialize_failed:
            materialize_failed = True
            raise RuntimeError("transient checkpoint failure")
        with checkpoint.execution_scope(
            value,
            applied_handoff_id=value.handoff_id,
            owner_scope="REQUEST_UNDERSTANDING",
            resume_target=target,
        ):
            graph.invoke(
                {"value": 0},
                config={"configurable": {"thread_id": value.effective_binding.langgraph_thread_id}},
                interrupt_before=["owner"],
            )
        result = checkpoint.load_same_run_checkpoint(
            value.effective_binding.run_id, value.effective_binding.langgraph_thread_id
        )
        assert result is not None
        if stale_on_checkpoint_store:
            with connect_sqlite(database_path) as connection:
                connection.execute("UPDATE runs SET version = version + 1 WHERE id = 'r-1';")
                connection.commit()
        return result

    class _CheckpointPort:
        def load_same_run_checkpoint(
            self, run_id: str, thread_id: str
        ) -> GraphCheckpointEnvelopeV1 | None:
            return checkpoint.load_same_run_checkpoint(run_id, thread_id)

        def store_same_run_checkpoint(self, value: GraphCheckpointEnvelopeV1) -> None:
            checkpoint.store_same_run_checkpoint(value)

        def flush(self) -> None:
            checkpoint.flush()

        def delete_run_checkpoints(self, run_id: str) -> None:
            checkpoint.delete_run_checkpoints(run_id)

    return (
        BackgroundRunExecutorAdapter(
            unit_of_work_factory=factory,
            checkpoint_port=cast(CheckpointPort, _CheckpointPort()),
            materialize_admission_checkpoint=materialize,
            invoke_semantic_owner=execute,
            release_active_lineage=lambda run_id, thread_id, handoff_id, run_sequence: (
                checkpoint.release_active_lineage(
                    run_id=run_id,
                    thread_id=thread_id,
                    handoff_id=handoff_id,
                    run_sequence=run_sequence,
                )
            ),
        ),
        database_path,
        checkpoint,
    )
