from __future__ import annotations

import ast
from pathlib import Path

from google_work_agent.adapters.langgraph.subgraphs.review.graph import (
    ReviewRuntimeDependencies,
    ReviewSubgraph,
)

ROOT = Path(__file__).resolve().parents[5]


def test_review_has_exact_five_runtime_nodes_and_supporting_validator_is_not_a_node() -> None:
    graph = ReviewSubgraph(
        dependencies=ReviewRuntimeDependencies(invoke=lambda _prompt_id, _input: {})
    ).build()
    assert set(graph.get_graph().nodes) - {"__start__", "__end__"} == {
        "inspect_goal_and_evidence",
        "inspect_action_scope_route",
        "inspect_constraints_policy",
        "aggregate_findings",
        "recheck",
    }
    source = (
        ROOT / "src/google_work_agent/adapters/langgraph/subgraphs/review/graph.py"
    ).read_text()
    assert 'graph.add_node("validate' not in source


def test_broad_and_pseudo_review_authorities_are_absent_from_production() -> None:
    removed = (
        "src/google_work_agent/adapters/langgraph/subgraphs/review/runtime_active_graph.py",
        "src/google_work_agent/adapters/langgraph/subgraphs/review/nodes/validate_review_node.py",
        "src/google_work_agent/adapters/langgraph/subgraphs/review/routing/route_after_validation.py",
        "src/google_work_agent/adapters/langgraph/workflow_providers.py",
        "src/google_work_agent/application/orchestration/inspect_plan_output.py",
        "src/google_work_agent/application/orchestration/review_invocation.py",
        "src/google_work_agent/application/orchestration/review_v2_tools.py",
    )
    assert all(not (ROOT / path).exists() for path in removed)
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "src/google_work_agent").rglob("*.py")
        if "controlled_post_retrieval.py" not in path.as_posix()
    )
    assert "RuntimeActiveReviewSubgraph" not in production
    assert "PlanReviewAgent" not in production
    assert "ThreeStageReviewSubgraph" not in production
    assert "_HistoricalPlanReviewEvaluator" not in production
    assert 'state.get("plan_review_result")' not in production


def test_main_and_all_profiles_bind_the_single_canonical_review_graph() -> None:
    workflow = (ROOT / "src/google_work_agent/adapters/langgraph/main/workflow.py").read_text()
    tree = ast.parse(workflow)
    imports = [
        node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module
    ]
    assert "google_work_agent.adapters.langgraph.subgraphs.review.graph" in imports
    assert (
        "google_work_agent.adapters.langgraph.subgraphs.review.runtime_active_graph" not in imports
    )
    assert "self._three_stage_review_subgraph = self._review_subgraph" in workflow
    assert "review_subgraph=self._review_subgraph" in workflow


def test_review_state_has_one_canonical_result_channel() -> None:
    canonical = (ROOT / "docs/canonical/06-agent-workflow.md").read_text(encoding="utf-8")
    state = (ROOT / "src/google_work_agent/adapters/langgraph/main/state.py").read_text()
    assert "plan_review: PlanReviewResultV2 | None" in canonical
    assert "plan_review_result:" not in state
