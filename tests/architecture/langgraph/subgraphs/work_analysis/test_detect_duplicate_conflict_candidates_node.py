from pathlib import Path


def test_detect_duplicate_conflict__candidates_exact_node__projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    assert (
        "project_detect_duplicate_conflict_candidates_input"
        in (owner / "nodes/detect_duplicate_conflict_candidates_node.py").read_text()
    )
    assert (owner / "projections/detect_duplicate_conflict_candidates_projection.py").exists()
    assert (
        'return "validate_relations"'
        in (owner / "routing/route_after_detect_duplicate_conflict_candidates.py").read_text()
    )
