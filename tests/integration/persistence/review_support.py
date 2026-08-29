from pathlib import Path

from google_work_agent.adapters.persistence.sqlite.unit_of_work import (
    SqliteUnitOfWork,
    sqlite_unit_of_work_factory,
)
from google_work_agent.application.use_cases.plan.record_review_result import (
    RecordReviewResultCommandV1,
    RecordReviewResultHandler,
)


def record_pass_review(database_path: Path, plan_id: str, *, now_ms: int = 1) -> None:
    """Record a real freshness-bound PASS for persistence integration setup."""

    with SqliteUnitOfWork(database_path) as unit_of_work:
        bundle = unit_of_work.plans.load_bundle(plan_id)
        if bundle is None:
            raise LookupError(f"plan not found: {plan_id}")
        review_version = bundle.plan.review_version
        action_versions = {action.id: action.version for action in bundle.actions}

    result = RecordReviewResultHandler(
        unit_of_work_factory=sqlite_unit_of_work_factory(database_path),
        now_ms=lambda: now_ms,
    )(
        RecordReviewResultCommandV1(
            command_id=f"review-pass-{plan_id}-{review_version}",
            plan_id=plan_id,
            expected_plan_version=bundle.plan.revision_no,
            expected_review_version=review_version,
            review_artifact_id=f"review-artifact-{plan_id}-{review_version}",
            review_version=review_version,
            disposition="PASS",
            based_on_action_versions=action_versions,
        )
    )
    if not result.applied:
        raise RuntimeError(result.conflict_detail or result.result_code)
