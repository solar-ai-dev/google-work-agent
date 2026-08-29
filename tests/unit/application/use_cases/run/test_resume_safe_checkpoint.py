"""Canonical safe-checkpoint replay and mismatch recovery proof."""

from importlib import import_module
from pathlib import Path
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.adapters.system.filesystem_operational_command_replay import (
    FilesystemOperationalCommandReplayAdapter,
)
from google_work_agent.adapters.system.sqlite_checkpoint import SqliteCheckpointAdapter
from google_work_agent.application.use_cases.run.resume_safe_checkpoint import (
    ResumeSafeCheckpointCommand,
    ResumeSafeCheckpointHandler,
)
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
)


def test_canonical_application_owner_is_importable() -> None:
    assert (
        import_module("google_work_agent.application.use_cases.run.resume_safe_checkpoint")
        is not None
    )


class _State(TypedDict):
    value: int


def test_safe_resume_replays_same_hash_and_rejects_different_hash(tmp_path: Path) -> None:
    database_path, registry = _database_with_checkpoint(tmp_path)
    scheduled: list[str] = []

    def schedule(command: object) -> RunExecutionAcceptedV1:
        scheduled.append(command.handoff_id)  # type: ignore[attr-defined]
        return RunExecutionAcceptedV1(1, True, "ACCEPTED")

    handler = ResumeSafeCheckpointHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        resume_target_registry=registry,
        schedule_run_execution=schedule,
        id_factory=lambda: "handoff-safe-1",
        operational_replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        now_ms=lambda: 20,
    )
    command = ResumeSafeCheckpointCommand("cmd-safe-1", "a" * 64, "r-1", 0)

    first = handler(command)
    replay = handler(command)
    conflict = handler(ResumeSafeCheckpointCommand("cmd-safe-1", "b" * 64, "r-1", 0))

    assert first.applied and replay.applied
    assert first.handoff_id == replay.handoff_id == "handoff-safe-1"
    assert scheduled == ["handoff-safe-1"]
    assert not conflict.applied
    assert conflict.result_code == "DUPLICATE_COMMAND"
    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        assert unit_of_work.workflow_handoffs.count_redriveable() == 1


def test_safe_resume_binding_mismatch_enters_durable_recovery(tmp_path: Path) -> None:
    database_path, registry = _database_with_checkpoint(tmp_path)
    with connect_sqlite(database_path) as connection:
        connection.execute(
            "UPDATE workflow_bindings SET graph_version='v2' WHERE run_id='r-1';"
        )
        connection.commit()
    handler = ResumeSafeCheckpointHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        resume_target_registry=registry,
        schedule_run_execution=lambda _command: RunExecutionAcceptedV1(1, True, "ACCEPTED"),
        id_factory=lambda: "unused",
        operational_replay=FilesystemOperationalCommandReplayAdapter(tmp_path / "replay"),
        now_ms=lambda: 20,
    )

    result = handler(ResumeSafeCheckpointCommand("cmd-mismatch", "c" * 64, "r-1", 0))

    assert result.applied
    assert result.run_status == "RECOVERY_REQUIRED"
    with sqlite_unit_of_work_factory(database_path)() as unit_of_work:
        context = unit_of_work.recovery_contexts.load_current_context("r-1")
    assert context is not None
    assert context["reason"] == "CHECKPOINT_MISMATCH"


def _database_with_checkpoint(tmp_path: Path) -> tuple[Path, ResumeTargetRegistry]:
    path = tmp_path / "safe-resume.db"
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
            ) VALUES ('r-1', 'c-1', 'AGENT_SEARCH', 'ANALYZING', 't-1',
                      'AUTO', NULL, '{}', 0, 1, NULL);
            """
        )
        connection.commit()
    checkpoint = SqliteCheckpointAdapter(path, now_ms=lambda: 10)
    checkpoint.create_workflow_binding(
        WorkflowBindingV1(1, "t-1", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", 1)
    )
    checkpoint.flush()
    registry = ResumeTargetRegistry(NodeRegistry(graph_version="v1"), "v1")
    target = registry.issue_main_stage("SIX_ROLE_BASELINE", "RETRIEVAL_ENTRY", "v1")
    admission = WorkflowExecutionAdmissionV1(
        1,
        "admission-1",
        "handoff-start",
        1,
        "NORMAL_HANDOFF",
        WorkflowExecutionBindingV1(
            1,
            "START",
            "r-1",
            "t-1",
            "SIX_ROLE_BASELINE",
            "v1",
            "AUTO",
            None,
            0,
            None,
        ),
        0,
    )
    builder = StateGraph(_State)
    builder.add_node("owner", lambda state: state)
    builder.add_edge(START, "owner")
    builder.add_edge("owner", END)
    graph = builder.compile(checkpointer=checkpoint)
    with checkpoint.execution_scope(
        admission,
        applied_handoff_id="handoff-start",
        owner_scope="MAIN_CONTROL",
        resume_target=target,
    ):
        graph.invoke(
            {"value": 0},
            config={"configurable": {"thread_id": "t-1"}},
            interrupt_before=["owner"],
        )
    checkpoint.flush()
    checkpoint.close()
    return path, registry
