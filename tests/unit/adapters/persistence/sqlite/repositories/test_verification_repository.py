import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.verification_repository import (
    SqliteVerificationRepository,
)
from google_work_agent.domain.verification.model import Verification, VerificationStatus


def test_verification_repository__latest_attempt__and_action_reads() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE approvals (id TEXT PRIMARY KEY, action_id TEXT);
        CREATE TABLE execution_attempts (id TEXT PRIMARY KEY, approval_id TEXT);
        CREATE TABLE verifications (
            id TEXT PRIMARY KEY, execution_attempt_id TEXT, verification_no INTEGER,
            status TEXT, normalizer_version TEXT, expected_json TEXT,
            actual_json TEXT, diff_json TEXT, verified_at_ms INTEGER
        );
        INSERT INTO approvals VALUES ('approval-1', 'action-1');
        INSERT INTO execution_attempts VALUES ('attempt-1', 'approval-1');
        """
    )
    repository = SqliteVerificationRepository(connection)
    for number in (1, 2):
        repository.insert(
            Verification(
                id=f"verification-{number}",
                execution_attempt_id="attempt-1",
                verification_no=number,
                status=VerificationStatus.VERIFIED,
                normalizer_version="1",
                expected_json="{}",
                actual_json="{}",
                diff_json="{}",
                verified_at_ms=number,
            )
        )

    latest = repository.get_latest_for_attempt("attempt-1")
    assert latest is not None and latest.verification_no == 2
    assert [item.verification_no for item in repository.list_for_action("action-1")] == [1, 2]
