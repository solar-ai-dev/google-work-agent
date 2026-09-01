from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.adapters.langgraph.subgraphs.planning.graph import (
    PlanningRuntimeDependencies,
    PlanningSubgraph,
)
from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)
from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    PlanningSemanticInvoker,
)
from google_work_agent.application.agents.review.contracts.review_findings import (
    ReviewSemanticInvoker,
)


def _inspection(prompt_id: str, findings: list[dict[str, object]]) -> dict[str, object]:
    return {"schema_version": 1, "dimension": prompt_id, "findings": findings}


def _finding(
    dimension: str,
    *,
    code: str,
    description: str,
    action_ids: list[str] | None = None,
    route_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "dimension": dimension,
        "code": code,
        "finding_kind": "ISSUE",
        "description": description,
        "evidence_refs": [],
        "affected_action_ids": action_ids or [],
        "affected_route_ids": route_ids or [],
        "required_information": [],
    }


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

    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke))
    ).build()
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
    assert result["final_result"] == {
        "schema_version": 2,
        "answer": "done",
        "evidence_refs": ["e1"],
    }
    assert calls == ["planning.outline_answer", "planning.compose_answer"]


def test_compiled_planning_graph_has_exact_six_runtime_nodes() -> None:
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=lambda _prompt_id, _input: {})
    ).build()
    assert set(graph.get_graph().nodes) - {"__start__", "__end__"} == {
        "outline_answer",
        "compose_answer",
        "draft_action_objective_per_output_route",
        "compose_arguments_per_output_route",
        "derive_dependencies",
        "assemble",
    }


def test_compiled_planning_action_executes_exact_four_node_path() -> None:
    route = {
        "route_id": "r1",
        "resource_type": "GMAIL_DRAFT",
        "connector_id": "google_workspace",
        "effect": "CREATE",
        "selected_tool_id": "gmail_create_draft",
        "reason_codes": ["USER_REQUEST"],
    }
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id.endswith("draft_action_objective_per_output_route"):
            return {
                "schema_version": 1,
                "route_id": "r1",
                "objective": "Create draft",
                "target_semantics": "GMAIL_DRAFT",
                "scope_constraints": ["draft only"],
                "evidence_refs": ["e1"],
            }
        return {
            "schema_version": 1,
            "route_id": "r1",
            "arguments": {"payload": {"to": ["a@example.com"], "subject": "s", "body": "b"}},
            "evidence_refs": ["e1"],
        }

    ids = iter(["action-1", "plan-1"])
    graph = PlanningSubgraph(
        dependencies=PlanningRuntimeDependencies(invoke=cast(PlanningSemanticInvoker, invoke)),
        id_factory=ids.__next__,
    ).build()
    result = graph.invoke(
        {
            "user_request": "Create a draft",
            "request_intent": {"goal": "create draft"},
            "tool_route_plan": {"output_plan": {"output_mode": "ACTION", "output_routes": [route]}},
            "evidence": [{"evidence_ref": "e1"}],
        }
    )
    assert result["final_result"]["actions"][0]["tool_id"] == "gmail_create_draft"
    assert calls == [
        "planning.draft_action_objective_per_output_route",
        "planning.compose_arguments_per_output_route",
    ]


def test_compiled_review_revise_emits_bounded_planning_revision_signal_without_recheck() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.inspect_action_scope_and_route":
            return _inspection(
                prompt_id,
                [
                    _finding(
                        prompt_id,
                        code="ACTION_NEEDS_REVISION",
                        description="revise action",
                        action_ids=["a1"],
                        route_ids=["r1"],
                    )
                ],
            )
        return _inspection(prompt_id, [])

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
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
            "code": "ACTION_NEEDS_REVISION",
            "description": "revise action",
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "affected_action_ids": ["a1"],
            "affected_route_ids": ["r1"],
            "evidence_refs": [],
        }
    ]
    assert result["workflow_signal"] is None
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
        return _inspection(prompt_id, [])

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
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
            "workflow_signal": None,
        }
    )
    assert result["review_result"]["status"] == "PASS"
    assert result["workflow_signal"] is None
    assert calls == [
        "review.inspect_goal_and_evidence",
        "review.inspect_constraints_and_policy_summary",
    ]


def test_compiled_review_recheck_refreshes_only_affected_dimensions() -> None:
    calls: list[str] = []

    def invoke(prompt_id: str, _prompt_input: Mapping[str, object]) -> Mapping[str, object]:
        calls.append(prompt_id)
        if prompt_id == "review.recheck_affected_dimensions":
            return {
                "schema_version": 1,
                "affected_dimensions": ["review.inspect_action_scope_and_route"],
                "findings": [
                    _finding(
                        "review.inspect_action_scope_and_route",
                        code="FRESH_ACTION_REVIEW",
                        description="fresh revised result",
                        action_ids=["a1"],
                        route_ids=["r1"],
                    )
                ],
            }
        raise AssertionError(f"unaffected dimension was rechecked: {prompt_id}")

    # This is exactly the bounded public issue shape carried by the REVISE signal;
    # RECHECK does not require private Review findings or required_information state.
    public_revision_issues = [
        {
            "dimension": "review.inspect_action_scope_and_route",
            "code": "STALE_ACTION_REVIEW",
            "finding_kind": "ISSUE",
            "description": "stale",
            "evidence_refs": [],
            "affected_action_ids": ["a1"],
            "affected_route_ids": ["r1"],
            "required_information": [],
        },
        {
            "dimension": "review.inspect_constraints_and_policy_summary",
            "code": "UNCHANGED_POLICY_REVIEW",
            "finding_kind": "ISSUE",
            "description": "unchanged",
            "evidence_refs": [],
            "affected_action_ids": [],
            "affected_route_ids": [],
            "required_information": [],
        },
    ]
    affected_action_ids = [
        action_id for issue in public_revision_issues for action_id in issue["affected_action_ids"]
    ]
    affected_route_ids = [
        route_id for issue in public_revision_issues for route_id in issue["affected_route_ids"]
    ]

    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=cast(ReviewSemanticInvoker, invoke))
    ).build()
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
            "affected_dimensions": ["review.inspect_action_scope_and_route"],
            "affected_action_ids": affected_action_ids,
            "affected_route_ids": affected_route_ids,
            "review_artifact_id": "rv2",
            "review_revision": 2,
            "review_based_on": [],
        }
    )
    assert calls == [
        "review.recheck_affected_dimensions",
    ]
    assert result["review_result"]["status"] == "REVISE"
    issues = result["review_result"]["issues"]
    codes = {issue["code"] for issue in issues}
    assert "FRESH_ACTION_REVIEW" in codes
    assert "UNCHANGED_POLICY_REVIEW" in codes
    assert "STALE_ACTION_REVIEW" not in codes
    assert next(issue for issue in issues if issue["code"] == "FRESH_ACTION_REVIEW") == {
        "code": "FRESH_ACTION_REVIEW",
        "description": "fresh revised result",
        "affected_dimensions": ["review.inspect_action_scope_and_route"],
        "affected_action_ids": ["a1"],
        "affected_route_ids": ["r1"],
        "evidence_refs": [],
    }
    assert next(issue for issue in issues if issue["code"] == "UNCHANGED_POLICY_REVIEW") == {
        "code": "UNCHANGED_POLICY_REVIEW",
        "description": "unchanged",
        "affected_dimensions": ["review.inspect_constraints_and_policy_summary"],
        "affected_action_ids": [],
        "affected_route_ids": [],
        "evidence_refs": [],
    }
