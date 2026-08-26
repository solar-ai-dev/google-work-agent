from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.ports.system.contracts.workflow_handoff import (
    RunExecutionRefV1,
    WorkflowExecutionAdmissionV1,
    WorkflowExecutionBindingV1,
    WorkflowHandoffStageV1,
)


def test_stage_pending_is_command_idempotent_and_allocates_same_run_sequence(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        first = unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        replay = unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        second = unit_of_work.workflow_handoffs.stage_pending(_stage("h-2", "cmd-2"))
        unit_of_work.commit()

    assert first == replay
    assert (first.run_sequence, second.run_sequence) == (1, 2)
    assert first.status == "PENDING"


def test_admission_claim_precedes_settlement_and_clears_one_shot_body(tmp_path: Path) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        admission = _admission(handoff.version, handoff.run_sequence)
        claimed = unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id, handoff.version, admission
        )
        settled = unit_of_work.workflow_handoffs.mark_consumed_and_clear_payload(
            claimed.handoff_id, claimed.version, admission.admission_id, "cp-1", 1
        )
        unit_of_work.commit()

    assert claimed.status == "DISPATCHED"
    assert claimed.execution_admission == admission
    assert settled.outcome == "SETTLED"
    assert settled.handoff.status == "CONSUMED"
    assert settled.handoff.execution_admission is None
    assert settled.handoff.applied_checkpoint_id == "cp-1"


def test_stale_run_epoch_retires_normal_admission_without_resurrecting_head(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        admission = _admission(handoff.version, handoff.run_sequence)
        claimed = unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id, handoff.version, admission
        )
        unit_of_work.commit()
    with connect_sqlite(database_path) as connection:
        connection.execute("UPDATE runs SET version = version + 1 WHERE id = 'r-1';")
        connection.commit()
    with factory() as unit_of_work:
        retired = unit_of_work.workflow_handoffs.release_execution_admission(
            claimed.handoff_id,
            claimed.version,
            admission.admission_id,
            "AUTHORITY_EPOCH_CHANGED",
        )
        head = unit_of_work.workflow_handoffs.get_dispatch_head("r-1")
        unit_of_work.commit()

    assert retired.status == "SUPERSEDED"
    assert retired.execution_admission is None
    assert head is None


def test_binding_mismatch_release_of_normal_admission_writes_blocked_binding(
    tmp_path: Path,
) -> None:
    database_path = _database(tmp_path)
    factory = sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10)
    with factory() as unit_of_work:
        handoff = unit_of_work.workflow_handoffs.stage_pending(_stage("h-1", "cmd-1"))
        admission = _admission(handoff.version, handoff.run_sequence)
        claimed = unit_of_work.workflow_handoffs.claim_execution_admission(
            handoff.handoff_id, handoff.version, admission
        )
        unit_of_work.commit()

    with factory() as unit_of_work:
        released = unit_of_work.workflow_handoffs.release_execution_admission(
            claimed.handoff_id,
            claimed.version,
            admission.admission_id,
            "BINDING_MISMATCH",
        )
        blocked = unit_of_work.workflow_handoffs.list_blocked_binding(10)
        head = unit_of_work.workflow_handoffs.get_dispatch_head("r-1")
        unit_of_work.commit()

    assert released.status == "BLOCKED_BINDING"
    assert released.execution_admission is None
    assert released.last_submit_reason == "BINDING_MISMATCH"
    assert [item.handoff_id for item in blocked] == ["h-1"]
    assert head is not None and head.handoff_id == "h-1"


def _database(tmp_path: Path) -> Path:
    path = tmp_path / "handoff.db"
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
        schema_version=1,
        handoff_id=handoff_id,
        trigger_command_id=command_id,
        execution=RunExecutionRefV1(
            schema_version=1,
            execution_kind="START",
            run_id="r-1",
            langgraph_thread_id="t-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            resume_target=None,
        ),
        checkpoint_id=None,
        checkpoint_generation=0,
        control_kind="NONE",
        control=None,
        control_payload_hash=None,
    )


def _admission(expected_version: int, run_sequence: int) -> WorkflowExecutionAdmissionV1:
    return WorkflowExecutionAdmissionV1(
        schema_version=1,
        admission_id="admission-1",
        handoff_id="h-1",
        handoff_run_sequence=run_sequence,
        submission_kind="NORMAL_HANDOFF",
        effective_binding=WorkflowExecutionBindingV1(
            schema_version=1,
            execution_kind="START",
            run_id="r-1",
            langgraph_thread_id="t-1",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
            requested_mode="AUTO",
            checkpoint_id=None,
            checkpoint_generation=0,
            resume_target=None,
        ),
        expected_run_version=expected_version,
    )
