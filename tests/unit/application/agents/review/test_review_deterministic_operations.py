from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.validate_review import validate_review


def test_review_aggregation_materializes_pass_and_revise_contracts() -> None:
    passed = aggregate_review_findings([], artifact_id="r1", revision=1)
    assert validate_review(passed)["status"] == "PASS"

    revised = aggregate_review_findings(
        [
            {
                "dimension": "ACTION_SCOPE_ROUTE",
                "code": "REVISION_REQUIRED",
                "description": "revise action",
                "action_id": "a1",
                "route_id": "r1",
                "required_information": [],
            }
        ],
        artifact_id="r2",
        revision=2,
    )
    validated = validate_review(revised)
    assert validated["status"] == "REVISE"
    assert validated["issues"] == [
        {
            "dimension": "ACTION_SCOPE_ROUTE",
            "code": "REVISION_REQUIRED",
            "description": "revise action",
            "action_id": "a1",
            "route_id": "r1",
        }
    ]


def test_review_pass_cannot_carry_issues() -> None:
    with pytest.raises(ValueError, match="keys"):
        validate_review(
            {
                "schema_version": 2,
                "meta": {"artifact_id": "r1", "revision": 1, "based_on": []},
                "status": "PASS",
                "summary": "ok",
                "issues": [],
            }
        )
