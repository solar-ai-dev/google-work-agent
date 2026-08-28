from __future__ import annotations

from collections.abc import Mapping

import pytest

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)


@pytest.mark.parametrize(
    ("dimension", "inspection_prompt"),
    [
        ("GOAL_EVIDENCE", "review.inspect_goal_and_evidence"),
        ("CONSTRAINTS_POLICY", "review.inspect_constraints_and_policy_summary"),
    ],
)
def test_public_dimension_only_revision_signal_drives_recheck(
    dimension: str, inspection_prompt: str
) -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            failure_record = prompt_input["failure_record"]
            assert isinstance(failure_record, Mapping)
            assert failure_record["affected_dimensions"] == [dimension]
            return {"affected_dimensions": [dimension]}
        if prompt_id == inspection_prompt:
            return {"findings": []}
        raise AssertionError(prompt_id)

    signal = {
        "kind": "PLANNING_REVISION_REQUIRED",
        "destination": "PLANNING",
        "disposition": "REVISE",
        "issues": [
            {
                "dimension": dimension,
                "code": "REVISION_REQUIRED",
                "description": "revise",
                "action_id": None,
                "route_id": None,
            }
        ],
    }
    result = (
        ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke))
        .build()
        .invoke(
            {
                "review_phase": "RECHECK",
                "request_intent": {"goal": "revise"},
                "tool_route_plan": {},
                "planning_result": {"revision": 2},
                "work_analysis": {},
                "evidence": [],
                "policy_summary": {},
                "prior_review_findings": [],
                "affected_action_ids": [],
                "affected_route_ids": [],
                "workflow_signal": signal,
                "review_artifact_id": "rv2",
                "review_revision": 2,
                "review_based_on": [],
            }
        )
    )

    assert calls == ["review.recheck_affected_dimensions", inspection_prompt]
    assert result["affected_dimension_recheck"] == ()
