from pathlib import Path

import pytest

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.tool_registry.load_signed_tool_registry import (
    load_signed_tool_registry,
)
from google_work_agent.application.use_cases.run.complete_answer_only_run import (
    CompleteAnswerOnlyRunCommand,
    CompleteAnswerOnlyRunHandler,
)
from google_work_agent.domain.resource_ref.model import ResourceRef
from google_work_agent.domain.results import ResultCode
from google_work_agent.domain.run.model import RunStatusV1


@pytest.fixture()
def answer_only_database(tmp_path: Path) -> Path:
    database_path = tmp_path / "answer-only.db"
    connection = connect_sqlite(database_path)
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            """
            INSERT INTO google_accounts (id, email, display_name, connected_at_ms)
            VALUES ('account-1', 'user@example.com', 'User', 1);
            """
        )
        connection.execute(
            """
            INSERT INTO conversations (id, account_id, title, created_at_ms, updated_at_ms)
            VALUES ('conversation-1', 'account-1', 'Conversation', 1, 1);
            """
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            )
            VALUES (
                'run-1', 'conversation-1', 'AGENT_SEARCH', 'ANALYZING', 'thread-1',
                'AUTO', '{}', 0, 100
            );
            """
        )
    finally:
        connection.close()
    return database_path


def test_answer_only__completion_is__atomic(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=0,
            request_hash="a" * 64,
        )
    )

    assert response.applied is True
    assert response.result_code is ResultCode.TRANSITION_APPLIED
    assert response.current_status is RunStatusV1.COMPLETED
    assert response.current_version == 1
    assert response.assistant_message_id == "message-1"

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute(
            """SELECT status, version, finished_at_ms, terminal_result_kind
               FROM runs WHERE id = 'run-1';"""
        ).fetchone()
        message = connection.execute(
            """
            SELECT id, role, content
            FROM messages
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        receipt = connection.execute(
            """
            SELECT status, result_code, result_version
            FROM command_receipts
            WHERE command_id = 'command-1';
            """
        ).fetchone()
        trace = connection.execute(
            """
            SELECT event_type, status, payload_json
            FROM trace_events
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        audit = connection.execute(
            """
            SELECT event_type, outcome
            FROM audit_events
            WHERE run_id = 'run-1';
            """
        ).fetchall()
        aggregate_counts = connection.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM plans WHERE run_id = 'run-1') AS plan_count,
                (SELECT COUNT(*) FROM actions) AS action_count,
                (SELECT COUNT(*) FROM approvals) AS approval_count,
                (SELECT COUNT(*) FROM execution_attempts) AS attempt_count,
                (SELECT COUNT(*) FROM verifications) AS verification_count;
            """
        ).fetchone()

        assert run["status"] == "COMPLETED"
        assert run["version"] == 1
        assert run["finished_at_ms"] == 1000
        assert run["terminal_result_kind"] == "SUCCESS"
        assert [(row["id"], row["role"], row["content"]) for row in message] == [
            ("message-1", "ASSISTANT", "done")
        ]
        assert receipt["status"] == "APPLIED"
        assert receipt["result_code"] == "TRANSITION_APPLIED"
        assert receipt["result_version"] == 1
        assert [(row["event_type"], row["status"]) for row in trace] == [
            ("COMMAND_APPLIED", "COMPLETED")
        ]
        assert '"schema_version": 1' in trace[0]["payload_json"]
        assert '"mode": "ANSWER_ONLY"' in trace[0]["payload_json"]
        assert '"message_id": "message-1"' in trace[0]["payload_json"]
        assert [(row["event_type"], row["outcome"]) for row in audit] == [
            ("RUN_COMPLETED", "TRANSITION_APPLIED")
        ]
        assert (
            '"schema_version": 1'
            in connection.execute(
                "SELECT metadata_json FROM audit_events WHERE run_id = 'run-1';"
            ).fetchone()[0]
        )
        assert tuple(aggregate_counts) == (0, 0, 0, 0, 0)
    finally:
        connection.close()


def test_answer_only__persists_selected_context__with_terminal_result(
    answer_only_database: Path,
) -> None:
    connection = connect_sqlite(answer_only_database)
    try:
        connection.execute(
            """
            INSERT INTO resource_refs (
                id, run_id, connector_id, resource_type, resource_id,
                captured_at_ms, metadata_json
            ) VALUES (
                'resource-1', 'run-1', 'google_workspace', 'gmail_thread',
                'thread-42', 10, '{}'
            );
            """
        )
    finally:
        connection.close()
    evidence_ids = iter(["evidence-persisted-1"])
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
        evidence_id_factory=lambda: next(evidence_ids),
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-context-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=0,
            request_hash="f" * 64,
            retrieval_artifact_id="retrieval-1",
            evidence_drafts=(
                {
                    "schema_version": 1,
                    "evidence_id": "logical-evidence-1",
                    "resource_handle": "gmail_thread:thread-42",
                    "segment_id": "segment-42",
                    "kind": "excerpt",
                    "excerpt": "From: sender@example.com\nSubject: request",
                    "locator": {},
                    "reason_codes": ["SUPPORTS"],
                },
            ),
        )
    )

    assert response.applied
    connection = connect_sqlite(answer_only_database)
    try:
        evidence = connection.execute(
            """
            SELECT id, resource_ref_id, excerpt, locator_json
            FROM evidence WHERE run_id = 'run-1';
            """
        ).fetchone()
        assert evidence["id"] == "evidence-persisted-1"
        assert evidence["resource_ref_id"] == "resource-1"
        assert evidence["excerpt"].startswith("From:")
        assert '"retrieval_artifact_id": "retrieval-1"' in evidence["locator_json"]
        assert '"role": "SUPPORTS"' in evidence["locator_json"]
    finally:
        connection.close()


def test_answer_only__persists_acquired_resource__with_search_evidence(
    answer_only_database: Path,
) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
        evidence_id_factory=lambda: "evidence-persisted-1",
        tool_registry=load_signed_tool_registry(),
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-search-context-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=0,
            request_hash="s" * 64,
            retrieval_artifact_id="retrieval-search-1",
            evidence_drafts=(
                {
                    "schema_version": 1,
                    "evidence_id": "logical-evidence-1",
                    "resource_handle": "gmail_thread:thread-search-42",
                    "segment_id": "segment-search-42",
                    "kind": "excerpt",
                    "excerpt": "From: sender@example.com\nSubject: request",
                    "locator": {},
                    "reason_codes": ["SUPPORTS"],
                },
            ),
            resource_ref_drafts=(
                ResourceRef(
                    id="resource-search-1",
                    run_id="run-1",
                    connector_id="google_workspace",
                    resource_type="gmail_thread",
                    resource_id="thread-search-42",
                    parent_resource_id=None,
                    canonical_url=None,
                    title="request",
                    event_time_ms=None,
                    version_token="v1",
                    metadata_json='{"title": "request"}',
                    captured_at_ms=900,
                ),
            ),
        )
    )

    assert response.applied
    connection = connect_sqlite(answer_only_database)
    try:
        resource = connection.execute(
            "SELECT id, connector_id, resource_type, resource_id FROM resource_refs;"
        ).fetchone()
        evidence = connection.execute(
            "SELECT resource_ref_id FROM evidence WHERE run_id = 'run-1';"
        ).fetchone()
        assert tuple(resource) == (
            "resource-search-1",
            "google_workspace",
            "gmail_thread",
            "thread-search-42",
        )
        assert evidence["resource_ref_id"] == "resource-search-1"
    finally:
        connection.close()


def test_same_command__id_and_hash__returns_stored_result(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )
    command = CompleteAnswerOnlyRunCommand(
        command_id="command-1",
        conversation_id="conversation-1",
        run_id="run-1",
        assistant_message="done",
        expected_version=0,
        request_hash="a" * 64,
    )

    first = service(command)
    second = service(command)

    assert second == first

    connection = connect_sqlite(answer_only_database)
    try:
        message_count = connection.execute(
            "SELECT COUNT(*) FROM messages WHERE run_id = 'run-1';"
        ).fetchone()[0]
        assert message_count == 1
    finally:
        connection.close()


def test_bounded_answer__only_completion_persists__and_replays_partial(
    answer_only_database: Path,
) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-partial",
    )
    command = CompleteAnswerOnlyRunCommand(
        command_id="command-partial",
        conversation_id="conversation-1",
        run_id="run-1",
        assistant_message="Only part of the request could be answered.",
        expected_version=0,
        request_hash="p" * 64,
        result_kind="PARTIAL",
    )

    first = service(command)
    replay = service(command)

    assert first.result_kind == "PARTIAL"
    assert replay == first
    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute(
            "SELECT terminal_result_kind FROM runs WHERE id='run-1';"
        ).fetchone()
        assert run["terminal_result_kind"] == "PARTIAL"
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM messages WHERE run_id='run-1' AND role='ASSISTANT';"
            ).fetchone()[0]
            == 1
        )
    finally:
        connection.close()


def test_same_command__id_and_different__hash_is_blocked(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=0,
            request_hash="a" * 64,
        )
    )
    duplicate = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-1",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=1,
            request_hash="b" * 64,
        )
    )

    assert duplicate.applied is False
    assert duplicate.result_code is ResultCode.DUPLICATE_COMMAND
    assert duplicate.current_status is RunStatusV1.COMPLETED

    connection = connect_sqlite(answer_only_database)
    try:
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 1
    finally:
        connection.close()


def test_stale_version__is_rejected__and_recorded(answer_only_database: Path) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-stale",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=5,
            request_hash="c" * 64,
        )
    )

    assert response.applied is False
    assert response.result_code is ResultCode.VERSION_CONFLICT
    assert response.current_status is RunStatusV1.ANALYZING
    assert response.current_version == 0

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute("SELECT status, version FROM runs WHERE id = 'run-1';").fetchone()
        receipt = connection.execute(
            """
            SELECT status, result_code
            FROM command_receipts
            WHERE command_id = 'command-stale';
            """
        ).fetchone()
        assert run["status"] == "ANALYZING"
        assert run["version"] == 0
        assert receipt["status"] == "REJECTED"
        assert receipt["result_code"] == "VERSION_CONFLICT"
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 0
    finally:
        connection.close()


def test_answer_only__rejects_oversized_terminal__input_before_uow(
    answer_only_database: Path,
) -> None:
    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 1000,
        message_id_factory=lambda: "message-1",
    )

    with pytest.raises(ValueError, match="1..65536 UTF-8 bytes"):
        service(
            CompleteAnswerOnlyRunCommand(
                command_id="command-fail",
                conversation_id="conversation-1",
                run_id="run-1",
                assistant_message="a" * 70000,
                expected_version=0,
                request_hash="d" * 64,
            )
        )

    connection = connect_sqlite(answer_only_database)
    try:
        run = connection.execute(
            "SELECT status, version, finished_at_ms FROM runs WHERE id = 'run-1';"
        ).fetchone()
        assert run["status"] == "ANALYZING"
        assert run["version"] == 0
        assert run["finished_at_ms"] is None
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM command_receipts WHERE command_id = 'command-fail';"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM trace_events;").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_events;").fetchone()[0] == 0
    finally:
        connection.close()


def test_received_receipt__is_recovered__from_completed_run(answer_only_database: Path) -> None:
    connection = connect_sqlite(answer_only_database)
    try:
        connection.execute(
            """
            UPDATE runs
            SET status = 'COMPLETED', version = 1, finished_at_ms = 1000
            WHERE id = 'run-1';
            """
        )
        connection.execute(
            """
            INSERT INTO messages (id, conversation_id, run_id, role, content, created_at_ms)
            VALUES ('message-1', 'conversation-1', 'run-1', 'ASSISTANT', 'done', 1000);
            """
        )
        connection.execute(
            """
            INSERT INTO command_receipts (
                command_id, command_type, request_hash, aggregate_type, aggregate_id,
                status, created_at_ms
            )
            VALUES (
                'command-pending', 'CompleteAnswerOnlyRun', ?, 'Run', 'run-1',
                'RECEIVED', 999
            );
            """,
            ("e" * 64,),
        )
    finally:
        connection.close()

    service = CompleteAnswerOnlyRunHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(answer_only_database),
        now_ms=lambda: 2000,
        message_id_factory=lambda: "message-2",
    )
    response = service(
        CompleteAnswerOnlyRunCommand(
            command_id="command-pending",
            conversation_id="conversation-1",
            run_id="run-1",
            assistant_message="done",
            expected_version=1,
            request_hash="e" * 64,
        )
    )

    assert response.applied is True
    assert response.current_status is RunStatusV1.COMPLETED
    assert response.assistant_message_id == "message-1"

    connection = connect_sqlite(answer_only_database)
    try:
        receipt = connection.execute(
            """
            SELECT status, result_code, completed_at_ms
            FROM command_receipts
            WHERE command_id = 'command-pending';
            """
        ).fetchone()
        assert receipt["status"] == "APPLIED"
        assert receipt["result_code"] == "TRANSITION_APPLIED"
        assert receipt["completed_at_ms"] == 2000
        assert connection.execute("SELECT COUNT(*) FROM messages;").fetchone()[0] == 1
    finally:
        connection.close()
