from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_planning_graph_has_no_generic_semantic_binding_authority() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/planning/graph.py")
    assert "PlanningNodeBindings" not in source
    assert "operation=bindings." not in source
    assert "PlanningRuntimeDependencies" in source
    assert "_inactive_invoke" not in source
    assert "choose_answer_or_action_from_route_node" not in source
    assert "route_after_outline_answer" in source
    assert "route_after_compose_answer" in source


def test_production_has_no_second_planning_answer_authority() -> None:
    optional_source = _source(
        "src/google_work_agent/application/orchestration/optional_agent_inputs.py"
    )
    provider_source = _source(
        "src/google_work_agent/adapters/langgraph/workflow_providers.py"
    )
    response_source = _source(
        "src/google_work_agent/adapters/langgraph/main/response_synthesis.py"
    )
    assert "CanonicalOptionalInputPlanningAgent" not in optional_source
    assert "invoke_answer_with_optional_analysis" not in optional_source
    assert "ProductionPlanningAnswerV2CandidateProvider" not in provider_source
    assert "build_production_planning_runtime" in response_source


def test_review_graph_has_no_generic_semantic_binding_authority() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/review/graph.py")
    assert "ReviewNodeBindings" not in source
    assert "operation=bindings." not in source
    assert "ReviewRuntimeDependencies" in source
    assert "invoke=self._dependencies.invoke" in source
    assert "route_after_entry" in source
    assert "route_after_validation" in source


def test_nodes_import_canonical_application_operations_directly() -> None:
    expected = {
        "planning": (
            "outline_answer",
            "compose_answer",
        ),
        "review": (
            "inspect_goal_and_evidence",
            "inspect_action_scope_and_route",
            "inspect_constraints_and_policy_summary",
            "aggregate_review_findings",
            "validate_review",
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


def test_review_revise_does_not_route_to_pre_revision_recheck() -> None:
    source = _source(
        "src/google_work_agent/adapters/langgraph/subgraphs/review/"
        "routing/route_after_validation.py"
    )
    assert 'return "end"' in source
    assert '"REVISE": "recheck_affected_dimensions"' not in source


def test_planning_review_nodes_do_not_execute_forbidden_boundaries() -> None:
    for owner in ("planning", "review"):
        node_dir = ROOT / f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}/nodes"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in node_dir.glob("*.py"))
        for forbidden in ("sqlite", "repository", "mcp", "provider"):
            assert forbidden not in combined.lower()
