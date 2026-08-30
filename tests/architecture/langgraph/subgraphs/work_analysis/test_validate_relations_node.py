from pathlib import Path


def test_validate_relations_exact_node_projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    assert (
        "project_validate_relations_input"
        in (owner / "nodes/validate_relations_node.py").read_text()
    )
    assert (owner / "projections/validate_relations_projection.py").exists()
    assert (
        'return "assess_information_gaps"'
        in (owner / "routing/route_after_validate_relations.py").read_text()
    )
