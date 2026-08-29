from pathlib import Path


def test_finalize_retrieval_has_exact_node_projection_and_terminal_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    node = (owner / "nodes/finalize_retrieval_node.py").read_text()
    assert "project_finalize_retrieval_input" in node
    assert (owner / "projections/finalize_retrieval_projection.py").exists()
    assert 'return "end"' in (owner / "routing/route_after_finalize_retrieval.py").read_text()
