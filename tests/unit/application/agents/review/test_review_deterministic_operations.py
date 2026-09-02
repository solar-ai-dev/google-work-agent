from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.validate_review import validate_review


def test_review_aggregation__materializes_pass__and_revise_contracts() -> None:
    passed = aggregate_review_findings([], artifact_id="r1", revision=1)
    assert validate_review(passed)["status"] == "PASS"

    revised = aggregate_review_findings(
        [
            {
                "dimension": "review.inspect_action_scope_and_route",
                "code": "REVISION_REQUIRED",
                "finding_kind": "ISSUE",
                "description": "revise action",
                "evidence_refs": ["e1"],
                "affected_action_ids": ["a1"],
                "affected_route_ids": ["r1"],
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
            "code": "REVISION_REQUIRED",
            "description": "revise action",
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "affected_action_ids": ["a1"],
            "affected_route_ids": ["r1"],
            "evidence_refs": ["e1"],
        }
    ]


def test_review_pass__cannot_carry__issues() -> None:
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
