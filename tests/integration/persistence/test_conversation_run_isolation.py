"""Integration tests for Conversation/Run Context Isolation (2026-08-19 Canonical,
docs/design/00-PROJECT-SOURCE-GUIDE.md "Conversation - Run 의미 경계").

A Conversation is a UI/persisted Timeline, not Agent semantic memory. After a
Run reaches a terminal status, a new USER request in the same conversation
must get a fresh run_id + langgraph_thread_id, and must not implicitly
inherit the prior Run's message/context. Only an open Run's own
Confirmation/Reauth/Recovery resumes the same Run.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.get_run_snapshot import (
    GetExecutionContextQuery,
    GetRunSnapshotHandler,
)
from google_work_agent.application.use_cases.run.start_run import (
    StartRunCommand,
    StartRunHandler,
)
from google_work_agent.domain.results import ResultCode
from tests.support.checkpoint import sqlite_checkpoint

_TOOL_REGISTRY = load_signed_tool_registry()


def _seeded_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "conversation-run-isolation.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, display_name, connected_at_ms) "
            "VALUES ('account-1', 'user@example.com', 'User', 1);"
        )
        connection.execute(
            "INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms) "
            "VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);"
        )
        connection.commit()
    finally:
        connection.close()
    return database_path


def _mark_run_terminal(database_path: Path, *, run_id: str, finished_at_ms: int) -> None:
    connection = connect_sqlite(database_path)
    try:
        connection.execute(
            "UPDATE runs SET status = 'COMPLETED', finished_at_ms = ? WHERE id = ?;",
            (finished_at_ms, run_id),
        )
        connection.commit()
    finally:
        connection.close()


def _handler(
    unit_of_work_factory: Callable[[], object], database_path: Path, *, now_ms: Callable[[], int]
) -> StartRunHandler:
    counter = itertools.count(1)
    return StartRunHandler(
        unit_of_work_factory=unit_of_work_factory,  # type: ignore[arg-type]
        checkpoint_port=sqlite_checkpoint(database_path),
        now_ms=now_ms,
        id_factory=lambda: f"id-{next(counter)}",
        graph_profile="SIX_ROLE_BASELINE",
        graph_version="resume-contract-v1",
        tool_registry=_TOOL_REGISTRY,
    )


def _command(*, command_id: str, request_hash: str, request_text: str) -> StartRunCommand:
    return StartRunCommand(
        command_id=command_id,
        request_hash=request_hash,
        conversation_id="conversation-1",
        request_text=request_text,
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        api_contract_version="1",
    )


def test_new_run_in__continuing_conversation_gets_fresh__run_and_thread_id(
    tmp_path: Path,
) -> None:
    """Case A: Run A completes (terminal) -> an independent new request in the
    same conversation gets a genuinely new run_id + langgraph_thread_id, and
    StartRun succeeds rather than hitting the open-run conflict."""
    database_path = _seeded_database(tmp_path)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    handler = _handler(unit_of_work_factory, database_path, now_ms=lambda: 1_000)

    run_a = handler(
        _command(command_id="command-a", request_hash="a" * 64, request_text="오늘 일정 알려줘")
    )
    assert run_a.applied is True
    _mark_run_terminal(database_path, run_id=run_a.run_id, finished_at_ms=2_000)

    run_b = handler(
        _command(command_id="command-b", request_hash="b" * 64, request_text="관련 메일 찾아줘")
    )

    assert run_b.applied is True
    assert run_b.run_id != run_a.run_id
    assert run_b.workflow_key != run_a.workflow_key

    connection = connect_sqlite(database_path)
    try:
        thread_ids = connection.execute(
            "SELECT id, langgraph_thread_id FROM runs ORDER BY started_at_ms ASC;"
        ).fetchall()
    finally:
        connection.close()
    assert [row["id"] for row in thread_ids] == [run_a.run_id, run_b.run_id]
    assert thread_ids[0]["langgraph_thread_id"] != thread_ids[1]["langgraph_thread_id"]


def test_new_run__execution_context_excludes__prior_run_content(tmp_path: Path) -> None:
    """Case B: Run B's RunExecutionContext (the source of its LLM prompt
    input) is built strictly from Run B's own run_id-scoped rows -- it must
    not surface Run A's request_text, even though both runs share the same
    conversation_id."""
    database_path = _seeded_database(tmp_path)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    handler = _handler(unit_of_work_factory, database_path, now_ms=lambda: 1_000)

    run_a = handler(
        _command(command_id="command-a", request_hash="a" * 64, request_text="오늘 일정 알려줘")
    )
    _mark_run_terminal(database_path, run_id=run_a.run_id, finished_at_ms=2_000)
    run_b = handler(
        _command(command_id="command-b", request_hash="b" * 64, request_text="관련 메일 찾아줘")
    )

    get_context = GetRunSnapshotHandler(unit_of_work_factory=unit_of_work_factory).execution_context
    context_a = get_context(GetExecutionContextQuery(run_a.run_id))
    context_b = get_context(GetExecutionContextQuery(run_b.run_id))

    assert context_a is not None
    assert context_b is not None
    assert context_a.request_text == "오늘 일정 알려줘"
    assert context_b.request_text == "관련 메일 찾아줘"
    assert context_b.request_text != context_a.request_text
    assert "일정" not in context_b.request_text


def test_start_run_rejects__second_open_run__in_same_conversation(tmp_path: Path) -> None:
    """Case C boundary: while Run A is still open (non-terminal), a second
    StartRun in the same conversation is rejected as STATE_CONFLICT rather
    than silently creating a second concurrent Run -- this is the
    uq_runs_one_open_per_conversation invariant the "runs 409" conflict
    response comes from."""
    database_path = _seeded_database(tmp_path)
    unit_of_work_factory = sqlite_unit_of_work_factory(database_path)
    handler = _handler(unit_of_work_factory, database_path, now_ms=lambda: 1_000)

    run_a = handler(
        _command(command_id="command-a", request_hash="a" * 64, request_text="오늘 일정 알려줘")
    )
    assert run_a.applied is True
    # Run A is left open (no _mark_run_terminal call) -- mirrors a Run still
    # mid-flight (CREATED/PLANNING/WAITING_CONFIRMATION/...).

    conflict = handler(
        _command(command_id="command-b", request_hash="b" * 64, request_text="관련 메일 찾아줘")
    )

    assert conflict.applied is False
    assert conflict.result_code == ResultCode.STATE_CONFLICT.value
    assert conflict.enqueued is False
    assert conflict.conflict_detail == "conversation already has an open run"

    with unit_of_work_factory() as unit_of_work:
        stored_run_a = unit_of_work.runs.get(run_a.run_id)
        stored_run_b = unit_of_work.runs.get(conflict.run_id)
    assert stored_run_a is not None
    assert stored_run_a.status.value == "CREATED"
    assert stored_run_b is None
