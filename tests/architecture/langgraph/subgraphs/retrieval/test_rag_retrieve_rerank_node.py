from pathlib import Path


def test_rag_retrieve_rerank_exact_node_projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert (
        "project_rag_retrieve_rerank_input"
        in (owner / "nodes/rag_retrieve_rerank_node.py").read_text()
    )
    assert (owner / "projections/rag_retrieve_rerank_projection.py").exists()
    assert (
        'return "select_evidence"'
        in (owner / "routing/route_after_rag_retrieve_rerank.py").read_text()
    )
