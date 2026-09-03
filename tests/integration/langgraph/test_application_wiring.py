from __future__ import annotations

from pathlib import Path

from google_work_agent.adapters.langgraph.main.nodes.initialize_node import initialize_node
from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.run.start_analysis import (
    StartAnalysisCommand,
    StartAnalysisHandler,
    StartAnalysisResult,
)


def test_initialize_node__calls_application_handler__and_persists_run_transition(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "langgraph-application-wiring.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection, now_ms=lambda: 1)
        connection.execute(
            "INSERT INTO google_accounts VALUES ('account-1', 'u@example.com', NULL, 1, NULL);"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Test', 1, 1);"
        )
        connection.execute(
            """
            INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'CREATED',
                      'thread-1', 'AUTO', '{}', 0, 1);
            """
        )
        connection.commit()

    handler = StartAnalysisHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path, now_ms=lambda: 10),
        now_ms=lambda: 10,
    )

    def start_analysis(run_id: str) -> StartAnalysisResult:
        return handler(
            StartAnalysisCommand(
                run_id=run_id,
                expected_version=0,
                command_id="start-analysis-1",
                request_hash="a" * 64,
            )
        )

    result = initialize_node(
        {"run_id": "run-1"},
        start_analysis=start_analysis,
        request_node="request_understanding",
    )

    assert result == {
        "workflow_phase": "REQUEST_ANALYSIS",
        "__logical_target__": "request_understanding",
        "__target__": "request_understanding",
    }
    with connect_sqlite(database_path) as connection:
        facts = connection.execute(
            """
            SELECT
                (SELECT status FROM runs WHERE id='run-1'),
                (SELECT status FROM command_receipts WHERE command_id='start-analysis-1'),
                (SELECT COUNT(*) FROM audit_events WHERE event_type='RUN_ANALYSIS_STARTED');
            """
        ).fetchone()
    assert tuple(facts) == ("ANALYZING", "APPLIED", 1)
