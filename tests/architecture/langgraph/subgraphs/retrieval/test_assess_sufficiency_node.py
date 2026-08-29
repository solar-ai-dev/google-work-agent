from pathlib import Path


def test_assess_sufficiency_has_exact_node_projection_and_bounded_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    node = (owner / "nodes/assess_sufficiency_node.py").read_text()
    assert "project_assess_sufficiency_input" in node
    assert (owner / "projections/assess_sufficiency_projection.py").exists()
    router = (owner / "routing/route_after_assess_sufficiency.py").read_text()
    assert 'return "plan_query"' in router
    assert 'return "finalize"' in router
