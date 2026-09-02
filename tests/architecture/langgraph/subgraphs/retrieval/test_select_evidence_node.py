from pathlib import Path


def test_select_evidence__has_exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_select_evidence_input" in (owner / "nodes/select_evidence_node.py").read_text()
    assert (owner / "projections/select_evidence_projection.py").exists()
    router = (owner / "routing/route_after_select_evidence.py").read_text()
    assert 'return "assess_sufficiency"' in router
