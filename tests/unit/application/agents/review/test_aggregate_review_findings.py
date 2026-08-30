from __future__ import annotations

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)


def _finding(kind: str) -> dict[str, object]:
    return {
        "dimension": "review.inspect_goal_and_evidence",
        "code": f"{kind}_CODE",
        "finding_kind": kind,
        "description": f"{kind} description",
        "evidence_refs": ["e1"],
        "affected_action_ids": ["a1"],
        "affected_route_ids": ["r1"],
        "required_information": ["more information"],
    }


def test_aggregate_review_findings_closes_all_six_exact_variants() -> None:
    expected = {
        None: "PASS",
        "ISSUE": "REVISE",
        "EVIDENCE_GAP": "RETRIEVE_MORE",
        "ROUTE_ISSUE": "ROUTE_RECONSIDERATION",
        "CONFIRMATION": "CONFIRM",
        "BLOCKER": "BLOCK",
    }
    for finding_kind, status in expected.items():
        result = aggregate_review_findings(
            [] if finding_kind is None else [_finding(finding_kind)],
            artifact_id=f"review-{status}",
            revision=1,
            based_on=[{"artifact_id": "plan-1", "revision": 1}],
        )
        assert result["status"] == status


def test_aggregate_review_findings_uses_closed_safety_precedence() -> None:
    result = aggregate_review_findings(
        [_finding("ISSUE"), _finding("CONFIRMATION"), _finding("BLOCKER")],
        artifact_id="review-1",
        revision=1,
    )
    assert result["status"] == "BLOCK"
