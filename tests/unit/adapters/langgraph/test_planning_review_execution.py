from __future__ import annotations

from collections.abc import Mapping

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)


def test_compiled_planning_answer_executes_canonical_operations() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "planning.outline_answer":
            assert set(prompt_input) == {
                "user_request",
                "request_intent",
                "work_analysis",
                "evidence",
            }
            return {"sections": ["summary"], "evidence_refs": ["e1"]}
        assert set(prompt_input) == {
            "user_request",
            "request_intent",
            "answer_outline",
            "work_analysis",
            "evidence",
        }
        return {"schema_version": 2, "answer": "done", "evidence_refs": ["e1"]}

    graph = PlanningSubgraph(dependencies=PlanningRuntimeDependencies(invoke=invoke)).build()
    result = graph.invoke(
        {
            "user_request": "Summarize it",
            "request_intent": {"goal": "summary"},
            "tool_route_plan": {"output_plan": {"output_mode": "ANSWER", "output_routes": []}},
            "work_analysis": {},
            "evidence": [{"evidence_ref": "e1"}],
        }
    )
    assert result["planning_disposition"] == "ANSWER"
    assert result["answer_outline"] == {"sections": ["summary"], "evidence_refs": ["e1"]}
    assert result["answer_draft"] == {
        "schema_version": 2,
        "answer": "done",
        "evidence_refs": ["e1"],
    }
    assert calls == ["planning.outline_answer", "planning.compose_answer"]


def test_compiled_planning_answer_graph_rejects_action_owned_by_successor() -> None:
    route = {
        "route_id": "r1",
        "resource_type": "TASK",
        "connector_id": "google_workspace",
        "effect": "UPDATE",
        "selected_tool_id": "tasks_update_task",
        "reason_codes": ["USER_REQUEST"],
    }
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=lambda _prompt_id, _prompt_input: {})
    ).build()
    import pytest

    with pytest.raises(ValueError, match="#118"):
        graph.invoke(
            {
                "user_request": "Update the task",
                "request_intent": {"goal": "update task"},
                "tool_route_plan": {
                    "output_plan": {"output_mode": "ACTION", "output_routes": [route]}
                },
            }
        )


def test_compiled_review_revise_emits_bounded_planning_revision_signal_without_recheck() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.inspect_action_scope_and_route":
            return {
                "findings": [
                    {
                        "code": "ACTION_NEEDS_REVISION",
                        "description": "revise action",
                        "action_id": "a1",
                        "route_id": "r1",
                    }
                ]
            }
        return {"findings": []}

    graph = ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke)).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": {"goal": "update task"},
            "tool_route_plan": {},
            "planning_result": {"actions": [{"action_id": "a1"}]},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "rv1",
            "review_revision": 1,
            "review_based_on": [],
        }
    )
    assert result["review_result"]["status"] == "REVISE"
    assert result["review_result"]["issues"] == [
        {
            "dimension": "ACTION_SCOPE_ROUTE",
            "code": "ACTION_NEEDS_REVISION",
            "description": "revise action",
            "action_id": "a1",
            "route_id": "r1",
        }
    ]
    assert result["workflow_signal"] == {
        "kind": "PLANNING_REVISION_REQUIRED",
        "destination": "PLANNING",
        "disposition": "REVISE",
        "issues": [
            {
                "dimension": "ACTION_SCOPE_ROUTE",
                "code": "ACTION_NEEDS_REVISION",
                "description": "revise action",
                "action_id": "a1",
                "route_id": "r1",
            }
        ],
    }
    assert "affected_dimension_recheck" not in result
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
        "review.inspect_constraints_and_policy_summary",
    ]
    assert "review.recheck_affected_dimensions" not in calls


def test_compiled_review_pass_does_not_emit_planning_revision_signal() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        return {"findings": []}

    graph = ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke)).build()
    result = graph.invoke(
        {
            "review_phase": "INITIAL",
            "request_intent": {"goal": "summarize"},
            "tool_route_plan": {},
            "planning_result": {"answer": "done"},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "review_artifact_id": "rv-pass",
            "review_revision": 1,
            "review_based_on": [],
            "workflow_signal": {
                "kind": "PLANNING_REVISION_REQUIRED",
                "destination": "PLANNING",
                "disposition": "REVISE",
                "issues": [],
            },
        }
    )
    assert result["review_result"]["status"] == "PASS"
    assert result["workflow_signal"] is None
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_action_scope_and_route",
        "review.inspect_constraints_and_policy_summary",
    ]


def test_compiled_review_recheck_refreshes_only_affected_dimensions() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            return {"affected_dimensions": ["ACTION_SCOPE_ROUTE"]}
        if prompt_id == "review.inspect_action_scope_and_route":
            return {
                "findings": [
                    {
                        "code": "FRESH_ACTION_REVIEW",
                        "description": "fresh revised result",
                        "action_id": "a1",
                        "route_id": "r1",
                    }
                ]
            }
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    # This is exactly the bounded public issue shape carried by the REVISE signal;
    # RECHECK does not require private Review findings or required_information state.
    public_revision_issues = [
        {
            "dimension": "ACTION_SCOPE_ROUTE",
            "code": "STALE_ACTION_REVIEW",
            "description": "stale",
            "action_id": "a1",
            "route_id": "r1",
        },
        {
            "dimension": "CONSTRAINTS_POLICY",
            "code": "UNCHANGED_POLICY_REVIEW",
            "description": "unchanged",
            "action_id": None,
            "route_id": None,
        },
    ]
    affected_action_ids = [
        issue["action_id"]
        for issue in public_revision_issues
        if isinstance(issue["action_id"], str)
    ]
    affected_route_ids = [
        issue["route_id"] for issue in public_revision_issues if isinstance(issue["route_id"], str)
    ]

    graph = ReviewSubgraph(dependencies=ReviewRuntimeDependencies(invoke=invoke)).build()
    result = graph.invoke(
        {
            "review_phase": "RECHECK",
            "request_intent": {"goal": "update task"},
            "tool_route_plan": {},
            "planning_result": {"revision": 2, "actions": [{"action_id": "a1"}]},
            "work_analysis": {},
            "evidence": [],
            "policy_summary": {},
            "prior_review_findings": public_revision_issues,
            "affected_action_ids": affected_action_ids,
            "affected_route_ids": affected_route_ids,
            "review_artifact_id": "rv2",
            "review_revision": 2,
            "review_based_on": [],
        }
    )
    assert calls == [
        "review.recheck_affected_dimensions",
        "review.inspect_action_scope_and_route",
    ]
    assert result["review_result"]["status"] == "REVISE"
    issues = result["review_result"]["issues"]
    codes = {issue["code"] for issue in issues}
    assert "FRESH_ACTION_REVIEW" in codes
    assert "UNCHANGED_POLICY_REVIEW" in codes
    assert "STALE_ACTION_REVIEW" not in codes
    assert next(issue for issue in issues if issue["code"] == "FRESH_ACTION_REVIEW") == {
        "dimension": "ACTION_SCOPE_ROUTE",
        "code": "FRESH_ACTION_REVIEW",
        "description": "fresh revised result",
        "action_id": "a1",
        "route_id": "r1",
    }
    assert next(issue for issue in issues if issue["code"] == "UNCHANGED_POLICY_REVIEW") == {
        "dimension": "CONSTRAINTS_POLICY",
        "code": "UNCHANGED_POLICY_REVIEW",
        "description": "unchanged",
        "action_id": None,
        "route_id": None,
    }
