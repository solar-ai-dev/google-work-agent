from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_planning_graph_registers_canonical_thin_nodes_and_router() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/planning/graph.py")
    for symbol in (
        "choose_answer_or_action_from_route_node", "outline_answer_node", "compose_answer_node",
        "draft_action_objective_per_output_route_node", "compose_arguments_per_output_route_node",
        "build_dependencies_node", "assemble_plan_node", "validate_plan_node",
    ):
        assert f"partial({symbol}," in source
    assert "route_after_disposition" in source
    assert "lambda state:" not in source
    assert "graph.add_node(\"choose_answer_or_action_from_route\", bindings." not in source


def test_review_graph_registers_canonical_thin_nodes_and_router() -> None:
    source = _source("src/google_work_agent/adapters/langgraph/subgraphs/review/graph.py")
    for symbol in (
        "inspect_goal_and_evidence_node", "inspect_action_scope_and_route_node",
        "inspect_constraints_and_policy_summary_node", "aggregate_review_findings_node",
        "validate_review_node", "recheck_affected_dimensions_node",
    ):
        assert f"partial({symbol}," in source
    assert "route_after_validation" in source
    assert "lambda state:" not in source
    assert "graph.add_node(\"inspect_goal_and_evidence\", bindings." not in source


def test_planning_review_nodes_do_not_execute_forbidden_boundaries() -> None:
    for owner in ("planning", "review"):
        node_dir = ROOT / f"src/google_work_agent/adapters/langgraph/subgraphs/{owner}/nodes"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in node_dir.glob("*.py"))
        for forbidden in ("sqlite", "repository", "mcp", "provider"):
            assert forbidden not in combined.lower()
