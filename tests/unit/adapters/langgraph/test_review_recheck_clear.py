from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)


def _run_recheck(
    *,
    prior: list[dict[str, object]],
    affected_dimensions: list[str],
    fresh_by_prompt: dict[str, list[dict[str, object]]],
) -> tuple[dict[str, object], list[str]]:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            return {"affected_dimensions": list(affected_dimensions)}
        if prompt_id in fresh_by_prompt:
            return {"findings": fresh_by_prompt[prompt_id]}
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    result = (
        ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke))
        .build()
        .invoke(
            {
                "review_phase": "RECHECK",
                "request_intent": {"goal": "revised"},
                "tool_route_plan": {},
                "planning_result": {"revision": 2},
                "work_analysis": {},
                "evidence": [],
                "policy_summary": {},
                "prior_review_findings": prior,
                "affected_dimensions": affected_dimensions,
                "affected_action_ids": [],
                "affected_route_ids": [],
                "review_artifact_id": "rv2",
                "review_revision": 2,
                "review_based_on": [],
            }
        )
    )
    return result, calls


def test_zero_fresh_findings_clear_stale_affected_dimension() -> None:
    result, calls = _run_recheck(
        prior=[
            {
                "dimension": "GOAL_EVIDENCE",
                "code": "STALE_GOAL",
                "description": "stale goal",
                "action_id": None,
                "route_id": None,
            }
        ],
        affected_dimensions=["GOAL_EVIDENCE"],
        fresh_by_prompt={"review.inspect_goal_and_evidence": []},
    )

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
    ]
    assert tuple(result["affected_dimensions"]) == ("GOAL_EVIDENCE",)
    assert result["review_result"]["status"] == "PASS"
    assert "issues" not in result["review_result"]


def test_zero_fresh_findings_preserve_unaffected_dimension() -> None:
    result, calls = _run_recheck(
        prior=[
            {
                "dimension": "GOAL_EVIDENCE",
                "code": "STALE_GOAL",
                "description": "stale goal",
                "action_id": None,
                "route_id": None,
            },
            {
                "dimension": "CONSTRAINTS_POLICY",
                "code": "UNCHANGED_POLICY",
                "description": "unchanged policy",
                "action_id": None,
                "route_id": None,
            },
        ],
        affected_dimensions=["GOAL_EVIDENCE"],
        fresh_by_prompt={"review.inspect_goal_and_evidence": []},
    )

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
    ]
    assert result["review_result"]["issues"] == [
        {
            "dimension": "CONSTRAINTS_POLICY",
            "code": "UNCHANGED_POLICY",
            "description": "unchanged policy",
            "action_id": None,
            "route_id": None,
        }
    ]


def test_fresh_finding_replaces_stale_affected_finding() -> None:
    result, calls = _run_recheck(
        prior=[
            {
                "dimension": "GOAL_EVIDENCE",
                "code": "STALE_GOAL",
                "description": "stale goal",
                "action_id": None,
                "route_id": None,
            }
        ],
        affected_dimensions=["GOAL_EVIDENCE"],
        fresh_by_prompt={
            "review.inspect_goal_and_evidence": [
                {
                    "code": "FRESH_GOAL",
                    "description": "fresh goal",
                    "action_id": None,
                    "route_id": None,
                }
            ]
        },
    )

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
    ]
    assert result["review_result"]["issues"] == [
        {
            "dimension": "GOAL_EVIDENCE",
            "code": "FRESH_GOAL",
            "description": "fresh goal",
            "action_id": None,
            "route_id": None,
        }
    ]


def test_mixed_affected_dimensions_replace_even_when_one_returns_no_findings() -> None:
    result, calls = _run_recheck(
        prior=[
            {
                "dimension": "GOAL_EVIDENCE",
                "code": "STALE_GOAL",
                "description": "stale goal",
                "action_id": None,
                "route_id": None,
            },
            {
                "dimension": "CONSTRAINTS_POLICY",
                "code": "STALE_POLICY",
                "description": "stale policy",
                "action_id": None,
                "route_id": None,
            },
            {
                "dimension": "ACTION_SCOPE_ROUTE",
                "code": "UNCHANGED_ACTION",
                "description": "unaffected action",
                "action_id": "a1",
                "route_id": "r1",
            },
        ],
        affected_dimensions=["GOAL_EVIDENCE", "CONSTRAINTS_POLICY"],
        fresh_by_prompt={
            "review.inspect_goal_and_evidence": [],
            "review.inspect_constraints_and_policy_summary": [
                {
                    "code": "FRESH_POLICY",
                    "description": "fresh policy",
                    "action_id": None,
                    "route_id": None,
                }
            ],
        },
    )

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
        "review.inspect_constraints_and_policy_summary",
    ]
    issues = result["review_result"]["issues"]
    assert {issue["code"] for issue in issues} == {"FRESH_POLICY", "UNCHANGED_ACTION"}
    assert "STALE_GOAL" not in {issue["code"] for issue in issues}
    assert "STALE_POLICY" not in {issue["code"] for issue in issues}
