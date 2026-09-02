from pathlib import Path


def test_build_query__exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_build_query_input" in (owner / "nodes/build_query_node.py").read_text()
    assert (owner / "projections/build_query_projection.py").exists()
    assert 'return "execute_read"' in (owner / "routing/route_after_build_query.py").read_text()
