from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.review.aggregate_review_findings import (
    aggregate_review_findings,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)
from google_work_agent.application.agents.review.inspect_action_scope_and_route import (
    inspect_action_scope_and_route,
)
from google_work_agent.application.agents.review.inspect_constraints_and_policy_summary import (
    inspect_constraints_and_policy_summary,
)
from google_work_agent.application.agents.review.inspect_goal_and_evidence import (
    inspect_goal_and_evidence,
)
from google_work_agent.application.agents.review.recheck_affected_dimensions import (
    recheck_affected_dimensions,
)
from google_work_agent.application.agents.review.validate_review import validate_review


def test_review_operation_inventory_is_6_of_6() -> None:
    assert all(
        callable(value)
        for value in (
            inspect_goal_and_evidence,
            inspect_action_scope_and_route,
            inspect_constraints_and_policy_summary,
            aggregate_review_findings,
            validate_review,
            recheck_affected_dimensions,
        )
    )


def test_recheck_genuinely_reinspects_only_affected_dimensions() -> None:
    prompt_calls: list[str] = []

    def invoke(prompt_id: str, _input: Mapping[str, object]) -> Mapping[str, object]:
        prompt_calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            return {
                "schema_version": 1,
                "affected_dimensions": ["review.inspect_action_scope_and_route"],
                "findings": [
                    {
                        "dimension": "review.inspect_action_scope_and_route",
                        "code": "fresh",
                        "finding_kind": "ROUTE_ISSUE",
                        "description": "fresh result",
                        "evidence_refs": [],
                        "affected_action_ids": [],
                        "affected_route_ids": ["r1"],
                        "required_information": [],
                    }
                ],
            }
        raise AssertionError(f"unexpected Prompt call: {prompt_id}")

    result = recheck_affected_dimensions(
        affected_dimensions=["review.inspect_action_scope_and_route"],
        affected_action_ids=[],
        affected_route_ids=["r1"],
        request_intent={},
        tool_route_plan={},
        planning_result={},
        evidence=[],
        invoke=cast(ReviewSemanticInvoker, invoke),
    )

    assert prompt_calls == [
        "review.recheck_affected_dimensions",
    ]
    assert result["affected_dimensions"] == ("review.inspect_action_scope_and_route",)
    assert result["findings"] and result["findings"][0]["code"] == "fresh"
    assert "review.inspect_constraints_and_policy_summary" not in prompt_calls
    assert "review.inspect_goal_and_evidence" not in prompt_calls


def test_three_review_inspection_authorities_remain_independent() -> None:
    assert (
        len(
            {
                id(inspect_goal_and_evidence),
                id(inspect_action_scope_and_route),
                id(inspect_constraints_and_policy_summary),
            }
        )
        == 3
    )
