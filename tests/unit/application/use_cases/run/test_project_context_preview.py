from __future__ import annotations

from json import dumps
from pathlib import Path

from google_work_agent.adapters.persistence.connection import connect_sqlite
from google_work_agent.adapters.persistence.migration import apply_migrations
from google_work_agent.adapters.persistence.sqlite.unit_of_work import sqlite_unit_of_work_factory
from google_work_agent.application.use_cases.run.project_context_preview import (
    ProjectContextPreviewHandler,
    ProjectContextPreviewQueryV1,
)
from google_work_agent.ports.system.contracts.retrieval_head import RetrievalHeadV1


class _Checkpoint:
    def load_retrieval_head(self, run_id: str) -> RetrievalHeadV1 | None:
        if run_id != "run-1":
            return None
        return RetrievalHeadV1(1, run_id, "thread-1", 7, "retrieval-current", "cp-1", 1)


def test_context_preview__contains_only_current__selected_retrieval_evidence(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "context-preview.db"
    with connect_sqlite(database_path) as connection:
        apply_migrations(connection)
        connection.execute(
            "INSERT INTO google_accounts (id, email, connected_at_ms) "
            "VALUES ('account-1', 'u@example.com', 1)"
        )
        connection.execute(
            "INSERT INTO conversations VALUES ('conversation-1', 'account-1', 'Inbox', 1, 1)"
        )
        connection.execute(
            """INSERT INTO runs (
                id, conversation_id, entry_mode, status, langgraph_thread_id,
                requested_mode, budget_json, version, started_at_ms
            ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'WAITING_APPROVAL',
                      'thread-1', 'AUTO', '{}', 4, 1)"""
        )
        connection.execute(
            """INSERT INTO plans (
                id, run_id, revision_no, status, summary_text, created_at_ms,
                review_status, review_version, review_disposition
            ) VALUES ('plan-1', 'run-1', 1, 'WAITING_APPROVAL', 'Plan', 2,
                      'PASSED', 1, 'PASS')"""
        )
        connection.execute(
            """INSERT INTO actions (
                id, plan_id, connector_id, position, tool_name, effect_type,
                approval_requirement, verification_policy, recovery_policy, status,
                arguments_json, arguments_hash, expected_json, created_at_ms, updated_at_ms
            ) VALUES ('action-1', 'plan-1', 'google_workspace', 1, 'tasks_create_task',
                      'CREATE', 'REQUIRED', 'GET_COMPARE', 'RESOURCE_SEARCH', 'PROPOSED',
                      '{}', ?, '{}', 3, 3)""",
            ("a" * 64,),
        )
        for ref_id, resource_id, title in (
            ("ref-current", "task-1", "Current task"),
            ("ref-stale", "task-2", "Stale task"),
        ):
            connection.execute(
                """INSERT INTO resource_refs (
                    id, run_id, connector_id, resource_type, resource_id,
                    title, metadata_json, captured_at_ms
                ) VALUES (?, 'run-1', 'google_workspace', 'task', ?, ?, '{}', 3)""",
                (ref_id, resource_id, title),
            )
        for evidence_id, ref_id, artifact, segment, role in (
            ("e-current", "ref-current", "retrieval-current", "segment-1", "SUPPORTS"),
            ("e-stale", "ref-stale", "retrieval-old", "segment-old", "CONTEXT"),
        ):
            connection.execute(
                """INSERT INTO evidence (
                    id, run_id, origin_type, resource_ref_id, kind, excerpt,
                    locator_json, created_at_ms
                ) VALUES (?, 'run-1', 'GOOGLE_RESOURCE', ?, 'excerpt', ?, ?, 3)""",
                (
                    evidence_id,
                    ref_id,
                    f"excerpt-{segment}",
                    dumps(
                        {
                            "retrieval_artifact_id": artifact,
                            "segment_id": segment,
                            "role": role,
                        }
                    ),
                ),
            )
    handler = ProjectContextPreviewHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        checkpoint=_Checkpoint(),  # type: ignore[arg-type]
    )

    result = handler(ProjectContextPreviewQueryV1("run-1"))

    assert result.retrieval_revision == 7
    assert [(item.segment_id, item.resource_id) for item in result.items] == [
        ("segment-1", "task-1")
    ]
    assert (result.gmail_count, result.tasks_count, result.calendar_count) == (0, 1, 0)
    assert result.adjustment_allowed is True
    assert result.allowed_adjustments == ("EXCLUDE_EVIDENCE", "RETRIEVE_MORE")
