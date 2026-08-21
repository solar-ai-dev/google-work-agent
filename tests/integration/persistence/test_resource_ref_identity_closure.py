import shutil
import sqlite3
from pathlib import Path

import pytest

from google_work_agent.adapters.persistence import apply_migrations, connect_sqlite
from google_work_agent.adapters.persistence.connector_identity import (
    ConnectorAwareResourceRefRepository,
)
from google_work_agent.ports import ResourceRefRecord, ResourceSource, StoredResourceType

RUNTIME_MIGRATIONS_DIR = Path("src/google_work_agent/adapters/persistence/migrations")


def test_clean_database_migrates_through_0008_with_full_integrity(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "clean-latest.db")
    try:
        results = apply_migrations(connection, now_ms=lambda: 1)

        assert results[-1].version == 8
        assert all(result.applied for result in results)
        assert [str(row[0]) for row in connection.execute("PRAGMA quick_check;")] == ["ok"]
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_0008_upgrade_preserves_plan_action_evidence_graph(tmp_path: Path) -> None:
    upgrade_dir = tmp_path / "upgrade-migrations"
    upgrade_dir.mkdir()
    for version in range(1, 8):
        source = next(RUNTIME_MIGRATIONS_DIR.glob(f"{version:04d}_*.sql"))
        shutil.copyfile(source, upgrade_dir / source.name)

    connection = connect_sqlite(tmp_path / "old-to-latest.db")
    try:
        apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 1)
        _seed_0007_aggregate_graph(connection)
        before = _aggregate_counts(connection)

        source = RUNTIME_MIGRATIONS_DIR / "0008_resource_ref_connector_identity.sql"
        shutil.copyfile(source, upgrade_dir / source.name)
        results = apply_migrations(connection, migrations_dir=upgrade_dir, now_ms=lambda: 2)

        assert results[-1].version == 8
        assert results[-1].applied is True
        assert _aggregate_counts(connection) == before
        assert connection.execute(
            "SELECT connector_id FROM resource_refs WHERE id = 'resource-1';"
        ).fetchone()[0] == "connector-a"
        assert connection.execute(
            "SELECT connector_id FROM actions WHERE id = 'action-1';"
        ).fetchone()[0] == "connector-a"
        assert connection.execute(
            "SELECT evidence_id FROM action_evidence WHERE action_id = 'action-1';"
        ).fetchone()[0] == "evidence-1"
        assert [str(row[0]) for row in connection.execute("PRAGMA quick_check;")] == ["ok"]
        assert connection.execute("PRAGMA foreign_key_check;").fetchall() == []
    finally:
        connection.close()


def test_same_source_and_external_id_coexist_across_connectors(tmp_path: Path) -> None:
    connection = connect_sqlite(tmp_path / "connector-coexist.db")
    try:
        apply_migrations(connection, now_ms=lambda: 1)
        _seed_run(connection)
        repository = ConnectorAwareResourceRefRepository(connection)

        repository.upsert(_event_ref("resource-a", "connector-a", title="A"))
        repository.upsert(_event_ref("resource-b", "connector-b", title="B"))

        rows = connection.execute(
            """
            SELECT connector_id, source, resource_type, resource_id, title
            FROM resource_refs
            WHERE run_id = 'run-1' AND resource_id = 'external-X'
            ORDER BY connector_id;
            """
        ).fetchall()
        assert [tuple(row) for row in rows] == [
            ("connector-a", "CALENDAR", "EVENT", "external-X", "A"),
            ("connector-b", "CALENDAR", "EVENT", "external-X", "B"),
        ]

        repository.upsert(_event_ref("replacement-id", "connector-a", title="A2"))
        rows_after_upsert = connection.execute(
            """
            SELECT id, connector_id, title FROM resource_refs
            WHERE run_id = 'run-1' AND resource_id = 'external-X'
            ORDER BY connector_id;
            """
        ).fetchall()
        assert [tuple(row) for row in rows_after_upsert] == [
            ("resource-a", "connector-a", "A2"),
            ("resource-b", "connector-b", "B"),
        ]

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO resource_refs (
                    id, run_id, connector_id, source, resource_type, resource_id,
                    metadata_json, captured_at_ms
                ) VALUES ('duplicate', 'run-1', 'connector-a', 'CALENDAR', 'EVENT',
                          'external-X', '{}', 2);
                """
            )
    finally:
        connection.close()


def _event_ref(record_id: str, connector_id: str, *, title: str) -> ResourceRefRecord:
    return ResourceRefRecord(
        id=record_id,
        run_id="run-1",
        connector_id=connector_id,
        source=ResourceSource.CALENDAR,
        resource_type=StoredResourceType.EVENT,
        resource_id="external-X",
        parent_resource_id=None,
        canonical_url=None,
        title=title,
        event_time_ms=None,
        version_token="v1",
        metadata_json="{}",
        captured_at_ms=1,
    )


def _seed_run(connection: sqlite3.Connection) -> None:
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
        ) VALUES ('run-1', 'conversation-1', 'AGENT_SEARCH', 'PLANNING',
                  'thread-1', 'AUTO', '{}', 0, 1);
        """
    )
    connection.commit()


def _seed_0007_aggregate_graph(connection: sqlite3.Connection) -> None:
    _seed_run(connection)
    connection.execute(
        """
        INSERT INTO plans (
            id, run_id, revision_no, status, summary_text, created_at_ms,
            review_status, review_version
        ) VALUES ('plan-1', 'run-1', 1, 'DRAFT', NULL, 1, 'PASSED', 0);
        """
    )
    connection.execute(
        """
        INSERT INTO resource_refs (
            id, run_id, connector_id, source, resource_type, resource_id,
            metadata_json, captured_at_ms
        ) VALUES ('resource-1', 'run-1', 'connector-a', 'CALENDAR', 'EVENT',
                  'external-X', '{}', 1);
        """
    )
    connection.execute(
        """
        INSERT INTO actions (
            id, plan_id, connector_id, position, tool_name, effect_type,
            approval_requirement, verification_policy, recovery_policy,
            target_resource_ref_id, status, arguments_json, arguments_hash,
            expected_json, risk_json, version, created_at_ms, updated_at_ms
        ) VALUES (
            'action-1', 'plan-1', 'connector-a', 1, 'calendar_update_event', 'UPDATE',
            'REQUIRED', 'GET_COMPARE', 'GET_TARGET', 'resource-1', 'PROPOSED',
            '{}', ?, '{}', '{}', 0, 1, 1
        );
        """,
        ("a" * 64,),
    )
    connection.execute(
        """
        INSERT INTO evidence (
            id, run_id, origin_type, resource_ref_id, message_id, kind,
            excerpt, locator_json, created_at_ms
        ) VALUES (
            'evidence-1', 'run-1', 'GOOGLE_RESOURCE', 'resource-1', NULL,
            'RESOURCE', 'bounded excerpt', NULL, 1
        );
        """
    )
    connection.execute(
        """
        INSERT INTO action_evidence (action_id, evidence_id)
        VALUES ('action-1', 'evidence-1');
        """
    )
    connection.commit()


def _aggregate_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = ("runs", "resource_refs", "plans", "actions", "evidence", "action_evidence")
    return {
        table: int(connection.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0])
        for table in tables
    }
