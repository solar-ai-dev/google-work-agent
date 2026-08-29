from pathlib import Path


def test_resolve_temporal_dependencies_exact_node_projection_and_router() -> None:
    owner = (
        Path(__file__).resolve().parents[5]
        / "src/google_work_agent/adapters/langgraph/subgraphs/work_analysis"
    )
    assert (
        "project_resolve_temporal_dependencies_input"
        in (owner / "nodes/resolve_temporal_dependencies_node.py").read_text()
    )
    assert (owner / "projections/resolve_temporal_dependencies_projection.py").exists()
    assert (
        'return "detect_duplicate_conflict_candidates"'
        in (owner / "routing/route_after_resolve_temporal_dependencies.py").read_text()
    )
