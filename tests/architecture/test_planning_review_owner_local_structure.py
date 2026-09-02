from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_planning_graph__has_no_generic__semantic_binding_authority() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/planning/graph.py")
    assert "PlanningNodeBindings" not in source
    assert "operation=bindings." not in source
    assert "PlanningRuntimeDependencies" in source
    assert "_inactive_invoke" not in source
    assert "choose_answer_or_action_from_route_node" not in source
    assert "route_after_outline_answer" in source
    assert "route_after_compose_answer" in source


def test_production_has__no_second__planning_answer_authority() -> None:
    optional_path = (
        ROOT / "src/google_work_agent/application/orchestration/optional_agent_inputs.py"
    )
    broad_assembler_path = (
        ROOT / "src/google_work_agent/application/orchestration/planning_plan_assembler.py"
    )
    provider_path = ROOT / "src/google_work_agent/adapters/langgraph/workflow_providers.py"
    response_source = _source("src/google_work_agent/adapters/langgraph/main/response_synthesis.py")
    assert not optional_path.exists()
    assert not broad_assembler_path.exists()
    assert not provider_path.exists()
    assert "build_production_planning_runtime" not in response_source
    assert "CanonicalOptionalPlanningSubgraph" not in response_source
    assert "_rebuild_six_role_graph_with_optional_subgraphs" not in response_source


def test_review_graph__has_no_generic__semantic_binding_authority() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/review/graph.py")
    assert "ReviewNodeBindings" not in source
    assert "operation=bindings." not in source
    assert "ReviewRuntimeDependencies" in source
    assert "return self._dependencies.invoke" in source
    assert "route_after_entry" in source
    assert "route_after_aggregate_review_findings" in source


def test_nodes_import__canonical_application__operations_directly() -> None:
    expected = {
        "planning": (
            "outline_answer",
            "compose_answer",
            "draft_action_objective_per_output_route",
            "compose_arguments_per_output_route",
            "build_dependencies",
            "assemble_plan",
        ),
        "review": (
            "inspect_goal_and_evidence",
            "inspect_action_scope_and_route",
            "inspect_constraints_and_policy_summary",
            "aggregate_review_findings",
            "recheck_affected_dimensions",
        ),
    }
    for owner, operations in expected.items():
        for operation in operations:
            source = _source(
                f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}/nodes/"
                f"{operation}_node.py"
            )
            assert f"application.agents.{owner}.{operation}" in source
            assert "operation: Callable" not in source
            assert "operation(projected)" not in source


def test_review_revise_does__not_route_to__pre_revision_recheck() -> None:
    source = _source(
        "src/google_work_agent/adapters/langgraph/subgraphs/review/"
        "routing/route_after_aggregate_review_findings.py"
    )
    assert 'return "end"' in source
    assert '"REVISE": "recheck_affected_dimensions"' not in source


def test_planning_review__nodes_do_not__execute_forbidden_boundaries() -> None:
    for owner in ("planning", "review"):
        node_dir = ROOT / f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}/nodes"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in node_dir.glob("*.py"))
        for forbidden in ("sqlite", "repository", "mcp", "provider api", "sdk"):
            assert forbidden not in combined.lower()
