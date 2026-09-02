from pathlib import Path


def test_execute_read__exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/retrieval"
    )
    assert "project_execute_read_input" in (owner / "nodes/execute_read_node.py").read_text()
    assert (owner / "projections/execute_read_projection.py").exists()
    assert (
        'return "normalize_segments"' in (owner / "routing/route_after_execute_read.py").read_text()
    )
