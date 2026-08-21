from __future__ import annotations

import pytest

from google_work_agent.application.agents.review.recheck_affected_dimensions import recheck_affected_dimensions
from google_work_agent.application.agents.review.validate_review import validate_review


def test_recheck_keeps_only_affected_action_findings_and_global_findings() -> None:
    findings = [
        {"code": "GLOBAL", "description": "global"},
        {"code": "A1", "description": "first", "action_id": "a1"},
        {"code": "A2", "description": "second", "action_id": "a2"},
    ]
    result = recheck_affected_dimensions(findings, affected_action_ids=["a2"])
    assert [item["code"] for item in result] == ["GLOBAL", "A2"]


def test_review_pass_cannot_carry_issues() -> None:
    with pytest.raises(ValueError, match="keys"):
        validate_review({
            "schema_version": 2,
            "meta": {"artifact_id": "r1", "revision": 1, "based_on": []},
            "status": "PASS",
            "summary": "ok",
            "issues": [],
        })
