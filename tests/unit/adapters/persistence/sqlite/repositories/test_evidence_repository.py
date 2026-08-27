import sqlite3

import pytest

from google_work_agent.adapters.persistence.sqlite.repositories.evidence_repository import (
    SqliteEvidenceRepository,
)
from google_work_agent.domain.evidence.model import Evidence, EvidenceOriginType


def test_evidence_repository_bounded_run_and_action_reads() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE evidence (
            id TEXT PRIMARY KEY, run_id TEXT, origin_type TEXT,
            resource_ref_id TEXT, message_id TEXT, kind TEXT, excerpt TEXT,
            locator_json TEXT, created_at_ms INTEGER
        );
        CREATE TABLE action_evidence (
            action_id TEXT, evidence_id TEXT,
            PRIMARY KEY (action_id, evidence_id)
        );
        """
    )
    repository = SqliteEvidenceRepository(connection)
    repository.insert_bounded(
        Evidence(
            id="evidence-1",
            run_id="run-1",
            origin_type=EvidenceOriginType.DERIVED,
            resource_ref_id=None,
            message_id=None,
            kind="SUMMARY",
            excerpt="safe excerpt",
            locator_json=None,
            created_at_ms=1,
        ),
        action_ids=("action-1",),
    )

    assert [item.id for item in repository.list_for_run("run-1")] == ["evidence-1"]
    assert [item.id for item in repository.list_for_action("action-1")] == ["evidence-1"]
    with pytest.raises(ValueError):
        repository.list_for_run("run-1", limit=501)
