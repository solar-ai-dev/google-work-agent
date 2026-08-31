import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.initial_workflow_binding_writer import (
    SqliteInitialWorkflowBindingWriter,
)
from google_work_agent.adapters.persistence.sqlite.unit_of_work import SqliteUnitOfWork
from google_work_agent.domain.conversation.model import Conversation
from google_work_agent.domain.run.model import RunCreate, RunStatusV1
from google_work_agent.ports.system.contracts.workflow_binding import WorkflowBindingV1

FORBIDDEN_SETUP_TABLES = (
    "workflow_bindings",
    "workflow_retrieval_heads",
    "workflow_external_llm_scopes",
)


def _migrated_database(path: Path) -> None:
    connection = connect_sqlite(path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) VALUES (?, ?, ?)",
            ("account-1", "account@example.com", 1),
        )
        connection.commit()
    finally:
        connection.close()


def test_write_and_read_uow_entry_execute_no_checkpoint_setup_sql(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "uow.db"
    _migrated_database(database_path)
    traces: list[str] = []

    from google_work_agent.adapters.persistence.sqlite import unit_of_work as uow_module

    real_connect = uow_module.connect_sqlite

    def traced_connect(path: Path) -> sqlite3.Connection:
        connection = real_connect(path)
        connection.set_trace_callback(traces.append)
        return connection

    monkeypatch.setattr(uow_module, "connect_sqlite", traced_connect)

    with SqliteUnitOfWork(database_path):
        pass
    with SqliteUnitOfWork(database_path, read_only=True):
        pass

    setup = [
        statement
        for statement in traces
        if statement.lstrip().upper().startswith(("CREATE ", "ALTER "))
        and any(table in statement.lower() for table in FORBIDDEN_SETUP_TABLES)
    ]
    assert setup == []


def test_initial_binding_writer_is_narrow_and_rolls_back_with_run(tmp_path: Path) -> None:
    database_path = tmp_path / "binding.db"
    _migrated_database(database_path)
    binding = WorkflowBindingV1(
        schema_version=1,
        workflow_key="workflow-1",
        run_id="run-1",
        langgraph_thread_id="thread-1",
        graph_profile="SINGLE_BASELINE",
        graph_version="1",
        requested_mode="AUTO",
        created_at_ms=1,
    )
    with SqliteUnitOfWork(database_path) as unit_of_work:
        assert isinstance(unit_of_work.workflow_bindings, SqliteInitialWorkflowBindingWriter)
        for method in (
            "load_workflow_binding",
            "store_same_run_checkpoint",
            "load_same_run_checkpoint",
            "store_retrieval_head",
            "store_external_llm_scope",
            "flush",
            "delete_run_checkpoints",
        ):
            assert not hasattr(unit_of_work.workflow_bindings, method)
        unit_of_work.conversations.create(
            Conversation(
                id="conversation-1",
                account_id="account-1",
                title="test",
                created_at_ms=1,
                updated_at_ms=1,
            )
        )
        unit_of_work.runs.create(
            RunCreate(
                id="run-1",
                conversation_id="conversation-1",
                entry_mode="AGENT_SEARCH",
                status=RunStatusV1.CREATED,
                langgraph_thread_id="thread-1",
                requested_mode="AUTO",
                actual_runtime=None,
                budget_json="{}",
                version=1,
                started_at_ms=1,
                finished_at_ms=None,
            )
        )
        unit_of_work.workflow_bindings.create_workflow_binding(binding)
        # No commit: both Run and binding must roll back together.

    connection = connect_sqlite(database_path)
    try:
        assert connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM workflow_bindings").fetchone()[0] == 0
    finally:
        connection.close()
