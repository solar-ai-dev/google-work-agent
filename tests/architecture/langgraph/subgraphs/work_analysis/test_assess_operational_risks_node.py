from pathlib import Path


def test_assess_operational_risks__has_exact_node__projection_and_router() -> None:
    owner = Path(__file__).resolve().parents[5] / (
        "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    node = (owner / "nodes/assess_operational_risks_node.py").read_text(encoding="utf-8")
    router = (owner / "routing/route_after_assess_operational_risks.py").read_text(encoding="utf-8")
    assert "project_assess_operational_risks_input" in node
    assert (owner / "projections/assess_operational_risks_projection.py").exists()
    assert 'return "finalize"' in router
