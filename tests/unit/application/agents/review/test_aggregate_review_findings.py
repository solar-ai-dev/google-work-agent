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


def test_aggregate_review__findings_closes_all__six_exact_variants() -> None:
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


def test_aggregate_review__findings_uses__closed_safety_precedence() -> None:
    result = aggregate_review_findings(
        [_finding("ISSUE"), _finding("CONFIRMATION"), _finding("BLOCKER")],
        artifact_id="review-1",
        revision=1,
    )
    assert result["status"] == "BLOCK"


def test_confirmation__does_not_promote_missing_information_to_executable_options() -> None:
    finding = _finding("CONFIRMATION")
    finding["description"] = "메일을 특정할 수 없습니다. 보낸 사람이나 제목을 알려 주시겠어요?"
    finding["required_information"] = ["CONFIRM_SENDER", "REFETCH_WITH_CORRECTION"]
    result = aggregate_review_findings([finding], artifact_id="review-1", revision=1)
    assert result["status"] == "CONFIRM"
    assert result["confirmation"] == {"question": finding["description"], "options": []}
