from pathlib import Path


def test_assess_information_gaps_has_exact_node_projection_and_router() -> None:
    owner = Path(__file__).resolve().parents[5] / (
        "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    node = (owner / "nodes/assess_information_gaps_node.py").read_text(encoding="utf-8")
    router = (owner / "routing/route_after_assess_information_gaps.py").read_text(encoding="utf-8")
    assert "project_assess_information_gaps_input" in node
    assert (owner / "projections/assess_information_gaps_projection.py").exists()
    assert '"assess_operational_risks"' in router
    assert '"finalize"' in router
