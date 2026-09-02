from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.validate_review import validate_review


def test_validate_review__accepts_exact__pass_contract() -> None:
    result = aggregate_review_findings([], artifact_id="review-1", revision=1)
    assert validate_review(result) == result


def test_validate_review__rejects_cross__variant_payload() -> None:
    result = aggregate_review_findings([], artifact_id="review-1", revision=1)
    invalid = {**result, "issues": []}
    with pytest.raises(ValueError, match="keys"):
        validate_review(invalid)
