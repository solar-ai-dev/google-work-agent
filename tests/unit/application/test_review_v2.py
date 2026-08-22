from __future__ import annotations

import pytest

from google_work_agent.application.orchestration.inspect_plan_output import (
    ReviewV2ValidationError,
    materialize_plan_review_result_v2,
    validate_plan_review_candidate_v2,
)


def _meta():
    return {
        "artifact_id": "review-1",
        "revision": 1,
        "based_on": [{"artifact_id": "plan-1", "revision": 1}],
    }


def test_pass_cannot_carry_confirmation() -> None:
    candidate = {
        "schema_version": 2,
        "status": "PASS",
        "summary": "ok",
        "confirmation": None,
    }
    with pytest.raises(ReviewV2ValidationError, match="keys mismatch"):
        validate_plan_review_candidate_v2(candidate)


def test_revise_materializes_only_canonical_issue_shape() -> None:
    candidate = {
        "schema_version": 2,
        "status": "REVISE",
        "issues": [
            {"code": "PLAN_WRONG_TARGET", "description": "wrong target", "action_id": "a1"}
        ],
    }
    result = materialize_plan_review_result_v2(candidate, meta=_meta())
    assert result == {"schema_version": 2, "meta": _meta(), **candidate}


def test_retrieve_more_uses_evidence_gaps_not_legacy_issues() -> None:
    candidate = {
        "schema_version": 2,
        "status": "RETRIEVE_MORE",
        "issues": [],
    }
    with pytest.raises(ReviewV2ValidationError, match="keys mismatch"):
        validate_plan_review_candidate_v2(candidate)


def test_block_requires_structured_blocker() -> None:
    with pytest.raises(ReviewV2ValidationError, match="at least one blocker"):
        validate_plan_review_candidate_v2(
            {"schema_version": 2, "status": "BLOCK", "blockers": []}
        )
