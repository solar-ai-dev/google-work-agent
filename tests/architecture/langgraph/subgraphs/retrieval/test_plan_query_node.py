from pathlib import Path


def test_plan_query__exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_plan_query_input" in (owner / "nodes/plan_query_node.py").read_text()
    assert (owner / "projections/plan_query_projection.py").exists()
    assert 'return "build_query"' in (owner / "routing/route_after_plan_query.py").read_text()
