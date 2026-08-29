"""Exact ownership smoke gate for the canonical Application module."""

from importlib import import_module
from pathlib import Path

from tests.support.fakes import DeterministicUUID

from google_work_agent.adapters.langgraph.registry.node_registry import NodeRegistry
from google_work_agent.adapters.langgraph.registry.resume_target_registry import (
    ResumeTargetRegistry,
)
from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.continue_cancel_resolution import (
    ContinueCancelResolutionResultV1,
)
from google_work_agent.application.use_cases.run.request_cancel import (
    RequestCancelCommand,
    RequestCancelHandler,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionAcceptedV1,
    RunExecutionRefV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowHandoffStageV1,
)


def test_canonical_application_owner_is_importable() -> None:
    assert import_module("google_work_agent.application.use_cases.run.request_cancel") is not None


def test_bootstrap_cancel_supersedes_unadmitted_start_then_uses_graphless_resolution(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        unit_of_work.workflow_handoffs.stage_pending(_start_handoff())
        unit_of_work.commit()
    continued: list[str] = []
    handler = _handler(
        factory,
        continue_cancel=lambda command: (
            continued.append(command.run_id)
            or ContinueCancelResolutionResultV1(1, "FINALIZED", "CANCELLED")
        ),
    )

    result = handler(RequestCancelCommand("r-1", 0, "cmd-cancel", "a" * 64))

    assert result.current_status == "CANCEL_REQUESTED"
    assert continued == ["r-1"]
    with factory() as unit_of_work:
        start = unit_of_work.workflow_handoffs.get("h-start")
    assert start is not None and start.status == "SUPERSEDED"


def test_bootstrap_cancel_preserves_admitted_start_and_waits_for_its_cancel_gate(
    tmp_path: Path,
) -> None:
    path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_start_handoff())
        unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id,
            handoff.version,
            WorkflowExecutionAdmissionV1(
                1,
                "admission-1",
                handoff.handoff_id,
                handoff.run_sequence,
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
            ),
        )
        unit_of_work.commit()
    continued: list[str] = []
    handler = _handler(
        factory,
        continue_cancel=lambda command: (
            continued.append(command.run_id)
            or ContinueCancelResolutionResultV1(1, "FINALIZED", "CANCELLED")
        ),
    )

    handler(RequestCancelCommand("r-1", 0, "cmd-cancel", "b" * 64))

    assert continued == []
    with factory() as unit_of_work:
        start = unit_of_work.workflow_handoffs.get("h-start")
    assert start is not None and start.status == "DISPATCHED"
    assert start.execution_admission is not None


def _handler(factory: object, *, continue_cancel: object) -> RequestCancelHandler:
    return RequestCancelHandler(
        unit_of_work_factory=factory,  # type: ignore[arg-type]
        now_ms=lambda: 10,
        id_generator=DeterministicUUID(prefix="handoff"),
        resume_target_registry=ResumeTargetRegistry(
            NodeRegistry(graph_version="v1"), "v1"
        ),
        schedule_run_execution=lambda _command: RunExecutionAcceptedV1(1, True, "ACCEPTED"),
        continue_cancel_resolution=continue_cancel,  # type: ignore[arg-type]
    )


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "request-cancel.db"
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


def _start_handoff() -> WorkflowHandoffStageV1:
    return WorkflowHandoffStageV1(
        1,
        "h-start",
        "cmd-start",
        RunExecutionRefV1(
            1, "START", "r-1", "t-1", "SIX_ROLE_BASELINE", "v1", "AUTO", None
        ),
        None,
        0,
        "NONE",
        None,
        None,
    )
