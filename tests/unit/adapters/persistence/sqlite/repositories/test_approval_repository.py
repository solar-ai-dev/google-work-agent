import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.approval_repository import (
    SqliteApprovalRepository,
)
from google_work_agent.domain.approval.model import Approval, ApprovalStatusV1


def test_approval_repository_exact_active_snapshot_and_cas_surface() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE actions (id TEXT PRIMARY KEY, plan_id TEXT);
        CREATE TABLE approvals (
            id TEXT PRIMARY KEY, action_id TEXT, approval_no INTEGER,
            action_version INTEGER, status TEXT, approved_by_account_id TEXT,
            approved_by_display TEXT, arguments_snapshot_json TEXT,
            canonical_arguments_hash TEXT, source_snapshot_json TEXT,
            source_snapshot_hash TEXT, policy_version TEXT,
            tool_schema_version TEXT, idempotency_key TEXT,
            recovery_fingerprint TEXT, approved_at_ms INTEGER,
            expires_at_ms INTEGER, consumed_at_ms INTEGER
        );
        INSERT INTO actions VALUES ('action-1', 'plan-1');
        """
    )
    repository = SqliteApprovalRepository(connection)
    repository.insert_active_snapshot(
        Approval(
            id="approval-1",
            action_id="action-1",
            approval_no=1,
            action_version=1,
            status=ApprovalStatusV1.ACTIVE,
            approved_by_account_id="account-1",
            approved_by_display="User",
            arguments_snapshot_json="{}",
            canonical_arguments_hash="a" * 64,
            source_snapshot_json="{}",
            source_snapshot_hash="b" * 64,
            policy_version="1",
            tool_schema_version="1",
            idempotency_key="c" * 64,
            recovery_fingerprint="d" * 64,
            approved_at_ms=1,
            expires_at_ms=2,
            consumed_at_ms=None,
        )
    )

    assert repository.get_active_for_action("action-1") is not None
    assert len(repository.list_active_for_plan("plan-1")) == 1
    assert repository.update_if_status(
        "approval-1",
        ApprovalStatusV1.ACTIVE,
        {"status": ApprovalStatusV1.CONSUMED, "consumed_at_ms": 2},
    )
    assert repository.get_active_for_action("action-1") is None
