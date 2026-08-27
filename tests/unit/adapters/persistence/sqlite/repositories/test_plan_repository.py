import sqlite3

from google_work_agent.adapters.persistence.sqlite.repositories.plan_repository import (
    SqlitePlanRepository,
)
from google_work_agent.domain.plan.model import Plan, PlanReviewStatus, PlanStatusV1


def test_plan_repository_exact_revision_review_and_status_cas_surface() -> None:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """CREATE TABLE plans (
            id TEXT PRIMARY KEY, run_id TEXT, revision_no INTEGER, status TEXT,
            summary_text TEXT, created_at_ms INTEGER, review_status TEXT,
            review_version INTEGER, review_disposition TEXT
        );
        CREATE TABLE actions (id TEXT PRIMARY KEY, plan_id TEXT);
        """
    )
    repository = SqlitePlanRepository(connection)
    repository.insert_revision(
        Plan(
            id="plan-1",
            run_id="run-1",
            revision_no=1,
            status=PlanStatusV1.DRAFT,
            summary_text="draft",
            created_at_ms=1,
        )
    )

    assert repository.get_current("run-1") == repository.load_bundle("plan-1")
    reviewed = repository.record_review_result(
        "plan-1",
        expected_review_version=0,
        expected_review_statuses=frozenset({PlanReviewStatus.PASSED}),
        values={
            "review_status": PlanReviewStatus.REQUIRED,
            "review_version": 1,
            "review_disposition": "review",
        },
    )
    assert reviewed is not None and reviewed.review_version == 1
    assert repository.update_if_version_and_status(
        "plan-1",
        1,
        frozenset({PlanStatusV1.DRAFT}),
        {"status": PlanStatusV1.ACTIVE},
    )
