from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)


def _base_state() -> dict[str, object]:
    return {
        "review_phase": "RECHECK",
        "request_intent": {"goal": "revise plan"},
        "tool_route_plan": {},
        "planning_result": {"revision": 2},
        "work_analysis": {},
        "evidence": [],
        "policy_summary": {},
        "affected_action_ids": [],
        "affected_route_ids": [],
        "review_artifact_id": "rv2",
        "review_revision": 2,
        "review_based_on": [],
    }


@pytest.mark.parametrize(
    ("dimension", "inspection_prompt", "fresh_code"),
    [
        ("GOAL_EVIDENCE", "review.inspect_goal_and_evidence", "FRESH_GOAL"),
        (
            "CONSTRAINTS_POLICY",
            "review.inspect_constraints_and_policy_summary",
            "FRESH_CONSTRAINTS",
        ),
    ],
)
def test_dimension_only_revise_freshly_rechecks_exact_public_dimension(
    dimension: str, inspection_prompt: str, fresh_code: str
) -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            failure_record = prompt_input["failure_record"]
            assert isinstance(failure_record, Mapping)
            assert failure_record["affected_dimensions"] == [dimension]
            assert failure_record["affected_action_ids"] == []
            assert failure_record["affected_route_ids"] == []
            assert failure_record["candidate_dimensions"] == [dimension]
            return {"affected_dimensions": [dimension]}
        if prompt_id == inspection_prompt:
            return {
                "findings": [
                    {
                        "code": fresh_code,
                        "description": "fresh revised result",
                        "action_id": None,
                        "route_id": None,
                    }
                ]
            }
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    state = _base_state()
    state.update(
        {
            "prior_review_findings": [
                {
                    "dimension": dimension,
                    "code": "STALE",
                    "description": "stale affected finding",
                    "action_id": None,
                    "route_id": None,
                }
            ],
            "affected_dimensions": [dimension],
        }
    )
    result = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=invoke)
    ).build().invoke(state)

    assert calls == ["review.recheck_affected_dimensions", inspection_prompt]
    assert result["review_result"]["issues"] == [
        {
            "dimension": dimension,
            "code": fresh_code,
            "description": "fresh revised result",
            "action_id": None,
            "route_id": None,
        }
    ]


def test_mixed_affected_scope_forms_deterministic_union_without_duplicate_inspection() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            failure_record = prompt_input["failure_record"]
            assert isinstance(failure_record, Mapping)
            assert failure_record["candidate_dimensions"] == [
                "GOAL_EVIDENCE",
                "ACTION_SCOPE_ROUTE",
            ]
            return {"affected_dimensions": ["ACTION_SCOPE_ROUTE", "GOAL_EVIDENCE"]}
        if prompt_id == "review.inspect_goal_and_evidence":
            return {"findings": []}
        if prompt_id == "review.inspect_action_scope_and_route":
            return {"findings": []}
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    state = _base_state()
    state.update(
        {
            "prior_review_findings": [
                {
                    "dimension": "ACTION_SCOPE_ROUTE",
                    "code": "STALE_ACTION",
                    "description": "stale action",
                    "action_id": "a1",
                    "route_id": "r1",
                }
            ],
            "affected_dimensions": ["GOAL_EVIDENCE", "GOAL_EVIDENCE"],
            "affected_action_ids": ["a1", "a1"],
            "affected_route_ids": ["r1", "r1"],
        }
    )
    ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke)).build().invoke(state)

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
    ]


def test_unaffected_prior_findings_are_preserved_and_not_rerun() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            return {"affected_dimensions": ["GOAL_EVIDENCE"]}
        if prompt_id == "review.inspect_goal_and_evidence":
            return {
                "findings": [
                    {
                        "code": "FRESH_GOAL",
                        "description": "fresh goal",
                        "action_id": None,
                        "route_id": None,
                    }
                ]
            }
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    state = _base_state()
    state.update(
        {
            "prior_review_findings": [
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
            "affected_dimensions": ["GOAL_EVIDENCE"],
        }
    )
    result = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=invoke)
    ).build().invoke(state)

    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_goal_and_evidence",
    ]
    codes = {issue["code"] for issue in result["review_result"]["issues"]}
    assert codes == {"FRESH_GOAL", "UNCHANGED_POLICY"}
    assert "STALE_GOAL" not in codes


def test_invalid_or_broadened_dimension_fails_closed() -> None:
    invalid_state = _base_state()
    invalid_state.update(
        {
            "prior_review_findings": [],
            "affected_dimensions": ["NOT_A_REVIEW_DIMENSION"],
        }
    )
    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(
            invoke=lambda _prompt_id, _prompt_input: {"affected_dimensions": []}
        )
    ).build()
    with pytest.raises(ValueError, match="invalid Review dimension"):
        graph.invoke(invalid_state)

    def broaden(_prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        return {"affected_dimensions": ["GOAL_EVIDENCE", "CONSTRAINTS_POLICY"]}

    broadened_state = _base_state()
    broadened_state.update(
        {
            "prior_review_findings": [],
            "affected_dimensions": ["GOAL_EVIDENCE"],
        }
    )
    broadened_graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=broaden)
    ).build()
    with pytest.raises(ValueError, match="canonical affected set"):
        broadened_graph.invoke(broadened_state)
